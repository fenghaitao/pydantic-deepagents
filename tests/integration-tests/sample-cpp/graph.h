#pragma once
#include <vector>
#include <unordered_map>
#include <string>

class Graph {
public:
    using NodeId = int;

    void addNode(NodeId id, const std::string& label);
    void addEdge(NodeId from, NodeId to, double weight = 1.0);
    std::vector<NodeId> neighbors(NodeId id) const;
    bool hasNode(NodeId id) const;
    std::size_t nodeCount() const;

private:
    struct Node {
        std::string label;
        std::vector<std::pair<NodeId, double>> edges;
    };
    std::unordered_map<NodeId, Node> nodes_;
};
