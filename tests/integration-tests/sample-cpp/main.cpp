#include <iostream>
#include "graph.h"

int main() {
    Graph g;
    g.addNode(1, "Alice");
    g.addNode(2, "Bob");
    g.addNode(3, "Carol");
    g.addEdge(1, 2, 0.8);
    g.addEdge(1, 3, 0.5);
    g.addEdge(2, 3, 0.9);

    for (auto n : g.neighbors(1)) {
        std::cout << "neighbor: " << n << "\n";
    }
    std::cout << "nodes: " << g.nodeCount() << "\n";
    return 0;
}
