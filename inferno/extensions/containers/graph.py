from collections import OrderedDict

import networkx as nx
from networkx import is_directed_acyclic_graph, topological_sort
from torch import nn as nn

from ...utils import python_utils as pyu


class NNGraph(nx.DiGraph):
    """A NetworkX DiGraph, except that node and edge ordering matters."""
    node_dict_factory = OrderedDict
    adjlist_dict_factory = OrderedDict


class Identity(nn.Module):
    """A torch.nn.Module to do nothing."""
    def forward(self, input):
        return input


class Graph(nn.Module):
    """
    A graph structure to build networks with complex architectures. The resulting graph model
    can be used like any other `torch.nn.Module`. The graph structure used behind the scenes
    is a `networkx.DiGraph`. This internal graph is exposed by the `apply_on_graph` method,
    which can be used with any NetworkX function (e.g. for plotting with matplotlib or GraphViz).

    Examples
    --------
    The naive inception module (without the max-pooling for simplicity) with ELU-layers of 64 units
    can be built as following, (assuming 64 input channels):

        >>> from inferno.extensions.layers.reshape import Concatenate
        >>> from inferno.extensions.layers.convolutional import ConvELU2D
        >>> import torch
        >>> from torch.autograd import Variable
        >>> # Build the model
        >>> inception_module = Graph()
        >>> inception_module.add_input_node('input')
        >>> inception_module.add_node('conv1x1', ConvELU2D(64, 64, 3), previous='input')
        >>> inception_module.add_node('conv3x3', ConvELU2D(64, 64, 3), previous='input')
        >>> inception_module.add_node('conv5x5', ConvELU2D(64, 64, 3), previous='input')
        >>> inception_module.add_node('cat', Concatenate(),
        >>>                           previous=['conv1x1', 'conv3x3', 'conv5x5'])
        >>> inception_module.add_output_node('output', 'cat')
        >>> # Build dummy variable
        >>> input = Variable(torch.rand(1, 64, 100, 100))
        >>> # Get output
        >>> output = inception_module(input)

    """
    def __init__(self, graph=None):
        """
        Construct the graph object.

        Parameters
        ----------
            graph : networkx.DiGraph or NNGraph
                Graph to build the object from (optional).
        """
        super(Graph, self).__init__()
        if graph is not None:
            assert isinstance(graph, nx.DiGraph)
            assert graph.node_dict_factory == OrderedDict
            assert graph.adjlist_dict_factory == OrderedDict
            self._graph = graph
        else:
            self._graph = NNGraph()

    def is_node_in_graph(self, name):
        """
        Checks whether a node is in the graph.

        Parameters
        ----------
        name : str
            Name of the node.

        Returns
        -------
        bool
        """
        return name in self._graph.node

    def is_source_node(self, name):
        """
        Checks whether a given node (by name) is a source node.
        A source node has no incoming edges.

        Parameters
        ----------
        name : str
            Name of the node.

        Returns
        -------
        bool

        Raises
        ------
        AssertionError
            if node is not found in the graph.
        """
        assert self.is_node_in_graph(name)
        return self._graph.in_degree(name) == 0

    def is_sink_node(self, name):
        """
        Checks whether a given node (by name) is a sink node.
        A sink node has no outgoing edges.

        Parameters
        ----------
        name : str
            Name of the node.

        Returns
        -------
        bool

        Raises
        ------
        AssertionError
            if node is not found in the graph.
        """
        assert self.is_node_in_graph(name)
        return self._graph.out_degree(name) == 0

    @property
    def output_nodes(self):
        """
        Gets a list of output nodes. The order is relevant and is the same as that
        in which the forward method returns its outputs.

        Returns
        -------
        list
            A list of names (str) of the output nodes.
        """
        return [name for name, node_attributes in self._graph.node.items()
                if node_attributes.get('is_output_node', False)]

    @property
    def input_nodes(self):
        """
        Gets a list of input nodes. The order is relevant and is the same as that
        in which the forward method accepts its inputs.

        Returns
        -------
        list
            A list of names (str) of the input nodes.
        """
        return [name for name, node_attributes in self._graph.node.items()
                if node_attributes.get('is_input_node', False)]

    @property
    def graph_is_valid(self):
        """Checks if the graph is valid."""
        # Check if the graph is a DAG
        is_dag = is_directed_acyclic_graph(self._graph)
        # Check if output nodes are sinks
        output_nodes_are_sinks = all([self.is_sink_node(name) for name in self.output_nodes])
        # Check inf input nodes are sources
        input_nodes_are_sources = all([self.is_source_node(name) for name in self.input_nodes])
        # TODO Check whether only input nodes are sources and only output nodes are sinks
        # Conclude
        is_valid = is_dag and output_nodes_are_sinks and input_nodes_are_sources
        return is_valid

    def assert_graph_is_valid(self):
        """Asserts that the graph is valid."""
        assert is_directed_acyclic_graph(self._graph), "Graph is not a DAG."
        for name in self.output_nodes:
            assert self.is_sink_node(name), "Output node {} is not a sink.".format(name)
            assert not self.is_source_node(name), "Output node {} is a source node. " \
                                                  "Make sure it's connected.".format(name)
        for name in self.input_nodes:
            assert self.is_source_node(name), "Input node {} is not a source.".format(name)
            assert not self.is_sink_node(name), "Input node {} is a sink node. " \
                                                "Make sure it's connected.".format(name)

    def add_node(self, name, module, previous=None):
        """
        Add a node to the graph.

        Parameters
        ----------
        name : str
            Name of the node. Nodes are identified by their names.

        module : torch.nn.Module
            Torch module for this node.

        previous : str or list of str
            (List of) name(s) of the previous node(s).

        Returns
        -------
        Graph
            self
        """
        assert isinstance(module, nn.Module)
        self.add_module(name, module)
        self._graph.add_node(name, module=module)
        if previous is not None:
            for _previous in pyu.to_iterable(previous):
                self.add_edge(_previous, name)
        return self

    def add_input_node(self, name):
        """
        Add an input to the graph. The order in which input nodes are added is the
        order in which the forward method accepts its inputs.

        Parameters
        ----------
        name : str
            Name of the input node.

        Returns
        -------
        Graph
            self
        """
        self.add_module(name, Identity())
        self._graph.add_node(name, is_input_node=True)
        return self

    def add_output_node(self, name, previous=None):
        """
        Add an output to the graph. The order in which output nodes are added is the
        order in which the forward method returns its outputs.

        Parameters
        ----------
        name : str
            Name of the output node.

        Returns
        -------
        Graph
            self
        """
        self._graph.add_node(name, is_output_node=True)
        if previous is not None:
            for _previous in pyu.to_iterable(previous):
                self.add_edge(_previous, name)
        return self

    def add_edge(self, from_node, to_node):
        """
        Add an edge between two nodes.

        Parameters
        ----------
        from_node : str
            Name of the source node.
        to_node : str
            Name of the target node.

        Returns
        -------
        Graph
            self

        Raises
        ------
        AssertionError
            if either of the two nodes is not in the graph,
            or if the edge is not 'legal'.
        """
        assert self.is_node_in_graph(from_node)
        assert self.is_node_in_graph(to_node)
        self._graph.add_edge(from_node, to_node)
        assert self.graph_is_valid
        return self

    def apply_on_graph(self, function, *args, **kwargs):
        """Applies a `function` on the internal graph."""
        return function(self, *args, **kwargs)

    def clear_payloads(self):
        for source, target in self._graph.edges_iter():
            if 'payload' in self._graph[source][target]:
                del self._graph[source][target]['payload']

    def forward_through_node(self, name, input=None):
        # If input is a tuple/list, it will NOT be unpacked.
        # Make sure the node is in the graph
        if input is None:
            # Make sure the node is not a source node
            assert not self.is_source_node(name), \
                "Node '{}' did not get an input but is a source node.".format(name)
            # Get input from payload
            incoming_edges = self._graph.in_edges(name)
            input = [self._graph[incoming][this]['payload']
                     for incoming, this in incoming_edges]
        else:
            assert self.is_node_in_graph(name)
            # Convert input to list
            input = [input]
        # Get outputs
        outputs = pyu.to_iterable(getattr(self, name)(*input))
        # Distribute outputs to outgoing payloads if required
        if not self.is_sink_node(name):
            outgoing_edges = self._graph.out_edges(name)
            if len(outputs) == 1:
                # Support for replication
                outputs *= len(outgoing_edges)
            # Make sure the number of outputs check out
            assert len(outputs) == len(outgoing_edges), \
                "Number of outputs from the model ({}) does not match the number " \
                "of out-edges ({}) in the graph for this node ('{}').".format(len(outputs),
                                                                              len(outgoing_edges),
                                                                              name)
            for (this, outgoing), output in zip(outgoing_edges, outputs):
                self._graph[this][outgoing].update({'payload': output})
        # Return outputs
        return pyu.from_iterable(outputs)

    def forward(self, *inputs):
        self.assert_graph_is_valid()
        input_nodes = self.input_nodes
        output_nodes = self.output_nodes
        assert len(inputs) == len(input_nodes), "Was expecting {} " \
                                                "arguments for as many input nodes, got {}."\
            .format(len(input_nodes), len(inputs))
        # Unpack inputs to input nodes
        for input, input_node in zip(inputs, input_nodes):
            self.forward_through_node(input_node, input=input)
        # Toposort the graph
        toposorted = topological_sort(self._graph)
        # Remove all input and output nodes
        toposorted = [name for name in toposorted
                      if name not in input_nodes and name not in output_nodes]
        # Forward
        for node in toposorted:
            self.forward_through_node(node)
        # Read outputs from output nodes
        outputs = []
        for output_node in output_nodes:
            # Get all incoming edges to output node
            outputs_from_node = [self._graph[incoming][this]['payload']
                                 for incoming, this in self._graph.in_edges(output_node)]
            outputs.append(pyu.from_iterable(outputs_from_node))
        # Clear payloads for next pass
        self.clear_payloads()
        # Done.
        return pyu.from_iterable(outputs)