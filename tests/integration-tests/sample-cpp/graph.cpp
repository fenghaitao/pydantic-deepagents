#include "graph.h"

void Graph::addNode(NodeId id, const std::string& label) {
    nodes_[id] = Node{label, {}};
}

void Graph::addEdge(NodeId from, NodeId to, double weight) {
    nodes_[from].edges.push_back({to, weight});
}

std::vector<Graph::NodeId> Graph::neighbors(NodeId id) const {
    std::vector<NodeId> result;
    auto it = nodes_.find(id);
    if (it != nodes_.end()) {
        for (auto& [neighbor, w] : it->second.edges)
            result.push_back(neighbor);
    }
    return result;
}

bool Graph::hasNode(NodeId id) const {
    return nodes_.count(id) > 0;
}

std::size_t Graph::nodeCount() const {
    return nodes_.size();
}
