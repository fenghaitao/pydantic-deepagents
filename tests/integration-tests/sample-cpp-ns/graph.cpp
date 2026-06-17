#include "graph.h"
#include <iostream>

namespace CodeAnalysis {

    // --- Node Implementation ---
    Graph::Node::Node(int node_id) : id(node_id) {}
    
    int Graph::Node::getId() const { 
        return id; 
    }

    // --- Edge Implementation ---
    Graph::Edge::Edge(int src, int tgt) : source_id(src), target_id(tgt) {}
    
    int Graph::Edge::getSource() const { 
        return source_id; 
    }
    
    int Graph::Edge::getTarget() const { 
        return target_id; 
    }

    // --- Graph Implementation ---
    void Graph::add_node(int node_id) {
        nodes.emplace_back(node_id);
    }

    void Graph::add_edge(int src, int tgt) {
        edges.emplace_back(src, tgt);
    }

    size_t Graph::count_node() const {
        return nodes.size();
    }

    size_t Graph::count_edge() const {
        return edges.size();
    }

    // --- CodeGraph Implementation ---
    CodeGraph::CodeGraph(const std::string& doc, const std::string& source)
        : Graph(), m_docstring(doc), m_source_code(source) {}

    std::string CodeGraph::docstring() const {
        return m_docstring;
    }

    std::string CodeGraph::source_code() const {
        return m_source_code;
    }

} // namespace CodeAnalysis
