You are a senior staff-level platform architect and principal frontend engineer.

I am building a fleet management and observability platform for approximately 40+ Mac Minis.

IMPORTANT CONSTRAINTS:
- I do NOT want to build a custom node agent.
- Node responsibilities MUST be handled using either:
  - Ansible
  - SaltStack
- This system is NOT intended to be a full MDM replacement.
- The system must focus on:
  - Fleet visibility
  - Configuration visibility
  - Drift detection
  - SBOM visibility
  - Group-based management
  - UI-driven operations
- Backend APIs will be consumed by a React frontend.
- Design for future scale to 1000+ nodes even though initial fleet is ~40 systems.

====================================================
HIGH LEVEL OBJECTIVE
====================================================

Design a production-grade architecture for a fleet management platform where:
- Ansible or SaltStack handles node execution/configuration
- The platform acts as:
  - observability layer
  - aggregation layer
  - drift analysis layer
  - SBOM explorer
  - frontend control plane

The system should provide:
- Aggregated fleet visibility
- Individual node visibility
- Grouping/tagging
- Drift detection
- Software inventory
- SBOM inspection
- Configuration run visibility
- Historical change tracking

====================================================
EXPECTED OUTPUT FORMAT
====================================================

Provide the response in the following structured sections:

1. Executive Summary
2. Recommended Architecture
3. Ansible vs SaltStack Analysis
4. Final Recommendation
5. High-Level System Diagram (ASCII)
6. Backend Architecture
7. Frontend Architecture
8. Database Design
9. API Design
10. Drift Detection Design
11. SBOM Pipeline Design
12. UI/UX Design
13. Security Considerations
14. Scalability Considerations
15. Failure Handling
16. GitOps Strategy
17. Recommended Tech Stack
18. Suggested Repository Structure
19. Future Enhancements
20. Risks and Tradeoffs

====================================================
DETAILED REQUIREMENTS
====================================================

====================================================
1. FLEET VISIBILITY
====================================================

The UI must provide:
- Total fleet overview
- Healthy/unhealthy systems
- Last check-in time
- OS versions
- Hardware visibility
- CPU/RAM/storage visibility
- Installed software inventory
- Running services
- Configuration status
- Drift score
- Recent configuration executions

The architecture must explain:
- How data is collected
- How data is normalized
- How data is stored
- How frontend consumes it

====================================================
2. GROUPING AND TAGGING
====================================================

The system must support:
- Logical grouping
- Labels/tags
- Dynamic grouping
- Environment grouping
- Role grouping

Examples:
- env=prod
- role=builder
- team=mobile
- location=blr

Explain:
- Data model
- Filtering architecture
- UI implementation
- API structure

====================================================
3. CONFIGURATION MANAGEMENT
====================================================

Node-level execution MUST rely on:
- Ansible OR SaltStack

DO NOT build a custom agent.

Explain:
- How configuration runs are triggered
- How outputs are collected
- How states are reported back
- How results are stored
- How failures are handled

Include:
- Pull vs push analysis
- Event-driven vs scheduled execution
- GitOps workflow

====================================================
4. DRIFT DETECTION
====================================================

The system must support drift detection between:
- Desired state
- Actual state

Drift examples:
- Missing packages
- Unauthorized packages
- Version mismatches
- Disabled/enabled services
- Configuration divergence

The design must include:
- Drift engine architecture
- Drift scoring model
- Historical drift timeline
- Diff visualization strategy
- Storage schema
- APIs

Explain:
- How desired state is defined
- How actual state is collected
- How diffs are computed

====================================================
5. SBOM VISIBILITY
====================================================

SBOM generation must use:
- Syft

The system must support:
- SBOM generation on nodes
- Centralized ingestion
- Searchable package inventory
- Fleet-wide package search
- Node-specific package search

Explain:
- SBOM format choice
- Storage model
- Indexing strategy
- Query optimization
- API design
- UI workflow

====================================================
6. FRONTEND REQUIREMENTS
====================================================

Frontend stack:
- React
- Tailwind
- Modern component architecture

The UI must include:
- Fleet dashboard
- Node detail page
- Drift visualization
- SBOM explorer
- Configuration execution history
- Group/tag explorer

For frontend architecture explain:
- Component hierarchy
- State management
- API consumption
- Caching
- Pagination
- Performance optimizations
- Rendering strategy for large datasets

====================================================
7. BACKEND REQUIREMENTS
====================================================

Backend responsibilities:
- Data ingestion
- Normalization
- Aggregation
- Drift computation
- SBOM indexing
- API serving

The design must include:
- Service boundaries
- Event flow
- Queue/event architecture
- Background jobs
- Scheduling
- Data lifecycle

====================================================
8. DATABASE DESIGN
====================================================

Design schemas for:
- Nodes
- Groups
- Tags
- Packages
- SBOM entries
- Drift records
- Execution history
- System facts
- Historical snapshots

Include:
- Relational schema suggestions
- Time-series considerations
- Indexing strategy
- Partitioning recommendations

====================================================
9. APIs
====================================================

Design REST APIs for:
- Fleet overview
- Node details
- Drift reports
- SBOM queries
- Execution history
- Group management

Provide:
- Endpoint definitions
- Request/response examples
- Filtering strategy
- Pagination strategy

====================================================
10. SECURITY
====================================================

Explain:
- Authentication
- RBAC
- Secrets handling
- Secure communication
- Node trust model
- Audit logging

====================================================
11. SCALABILITY
====================================================

Design for future scale:
- 40 nodes now
- 1000+ later

Explain:
- Bottlenecks
- Event scaling
- API scaling
- DB scaling
- UI scaling

====================================================
12. TECHNOLOGY DECISIONS
====================================================

You MUST provide:
- Strong recommendations
- Tradeoffs
- Opinionated architecture choices

DO NOT provide generic “it depends” answers.

Where applicable explain:
- Why SaltStack may be better than Ansible
- Why Ansible may be simpler
- When event-driven systems matter
- When pull mode is preferred

====================================================
13. OUTPUT EXPECTATIONS
====================================================

The response must:
- Be implementation-oriented
- Be deeply technical
- Be production-grade
- Avoid vague recommendations
- Avoid generic architecture advice
- Include diagrams, schemas, and examples
- Include operational considerations
- Include DevSecOps considerations

====================================================
14. IMPORTANT CONSTRAINTS
====================================================

DO NOT:
- Suggest JAMF as the primary solution
- Suggest building a custom agent
- Give shallow frontend advice
- Give generic cloud-native buzzwords without explanation

DO:
- Focus on practical implementation
- Focus on fleet operations
- Focus on observability
- Focus on frontend usability
- Focus on drift detection quality
- Focus on scalable backend design
- Focus on maintainability

====================================================
15. EXPECTED DEPTH
====================================================

Assume the audience is:
- Senior DevOps engineers
- Platform engineers
- SREs
- DevSecOps architects

The answer should resemble:
- A real architecture design review
- An internal engineering RFC
- A staff-level system design document
