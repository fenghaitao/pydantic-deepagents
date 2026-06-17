#include "graph.h"
#include <iostream>

int main() {
    // Define sample metadata
    std::string doc = "This graph represents a basic control flow of an if-else statement.";
    std::string code = "if (x > 0) { foo(); } else { bar(); }";

    // Create a CodeGraph instance inside the CodeAnalysis namespace
    CodeAnalysis::CodeGraph cg(doc, code);

    // Add two nodes
    cg.add_node(1); // e.g., Entry Block
    cg.add_node(2); // e.g., Branch Block

    // Add an edge connecting them
    cg.add_edge(1, 2);

    // Output results to verify correctness
    std::cout << "=== CodeGraph Metrics ===" << std::endl;
    std::cout << "Node count: " << cg.count_node() << std::endl;
    std::cout << "Edge count: " << cg.count_edge() << std::endl;
    
    std::cout << "\n=== CodeGraph Metadata ===" << std::endl;
    std::cout << "Docstring:\n  " << cg.docstring() << std::endl;
    std::cout << "Source Code:\n  " << cg.source_code() << std::endl;

    return 0;
}
