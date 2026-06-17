#ifndef GRAPH_H
#define GRAPH_H

#include <string>
#include <vector>

namespace CodeAnalysis {

    class Graph {
    public:
        // Nested Node Class
        class Node {
        private:
            int id;
        public:
            Node(int node_id);
            int getId() const;
        };

        // Nested Edge Class
        class Edge {
        private:
            int source_id;
            int target_id;
        public:
            Edge(int src, int tgt);
            int getSource() const;
            int getTarget() const;
        };

    protected:
        std::vector<Node> nodes;
        std::vector<Edge> edges;

    public:
        Graph() = default;
        virtual ~Graph() = default;

        void add_node(int node_id);
        void add_edge(int src, int tgt);
        
        size_t count_node() const;
        size_t count_edge() const;
    };

    // CodeGraph inherits from Graph
    class CodeGraph : public Graph {
    private:
        std::string m_docstring;
        std::string m_source_code;

    public:
        CodeGraph(const std::string& doc, const std::string& source);

        std::string docstring() const;
        std::string source_code() const;
    };

} // namespace CodeAnalysis

#endif // GRAPH_H
