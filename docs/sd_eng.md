**SYSTEM SPECIFICATION: AUTONOMOUS GEOGRAPHIC SYSTEM DYNAMICS SYNTHESIS ENGINE (AGSDSE)**

**1. Input Specification**
- Primary input: Closed geospatial boundary polygon (WGS84/UTM).
- Implicit resolution: System autonomously intersects boundary with administrative, hydrological, ecological, infrastructural, and functional layers to generate multi-resolution spatial tessellation. No additional user parameters required.

**2. Domain Taxonomy & State-Space Formalism**
Each domain is encoded as a typed node cluster with conservation constraints, stock/flow archetypes, and cross-domain transfer operators.
- **Political & Institutional:** Stocks (legitimacy indices, institutional capacity, bureaucratic headcount); Flows (policy enactment, turnover, reform, compliance drift); Coupling (modulates transaction costs, gates resource allocation, shapes conflict thresholds).
- **Economic & Financial:** Stocks (capital vintages, debt/equity ratios, monetary aggregates, asset valuations); Flows (investment, credit expansion, depreciation, default, capital flight); Coupling (SFC accounting, liquidity constraints, leverage feedback, real-economy amplification).
- **Social & Demographic:** Stocks (age-sex cohorts, household distributions, welfare dependency, social capital); Flows (fertility, mortality, migration, aging, network formation); Coupling (Leslie projections, density-dependent vital rates, labor supply elasticity).
- **Ethnological & Cultural:** Stocks (norm internalization, intergroup trust, narrative salience, identity boundary permeability); Flows (cultural transmission, assimilation, radicalization, media exposure); Coupling (contagion kernels, bounded rationality operators, belief-updating functions).
- **Biophysical & Ecological:** Stocks (biomass pools, soil organic carbon, groundwater/surface reservoirs); Flows (precipitation, evapotranspiration, runoff, decomposition, extraction); Coupling (mass/energy conservation, carrying capacity gates, climate-forcing downscaling).
- **Technological & Infrastructural:** Stocks (asset condition indices, network capacity, vintage distribution); Flows (maintenance, obsolescence, deployment, failure/repair); Coupling (diffusion-adoption kinetics, cascading reliability, spatial accessibility gradients).
- **Epidemiological & Public Health:** Stocks (SEIR compartments, chronic disease prevalence, healthcare workforce); Flows (infection, recovery, treatment initiation, health system saturation); Coupling (contact matrices, mortality/vital rate modulation, policy responsiveness windows).
- **Legal & Regulatory:** Stocks (statutory corpus, enforcement capacity, judicial backlog, compliance rates); Flows (legislation, adjudication, penalty issuance, institutional drift); Coupling (procedural delay chains, regulatory capture dynamics, conflict mediation).
- **Spatial & Land-Use/Mobility:** Stocks (built density, land cover classes, transport/freight capacity); Flows (conversion, development pressure, commute routing, agglomeration/dispersion); Coupling (gravity/routing models, cellular automata, territorial fragmentation).
- **Material & Energy Metabolism:** Stocks (material inventories by sector, energy carriers, waste sinks); Flows (extraction, refining, consumption, recycling, emissions); Coupling (MFA accounting, exergy limits, circularity deficits, EROI tracking).
- **Security & Conflict:** Stocks (force readiness, threat intensity, radicalization pools, crime prevalence); Flows (recruitment, deployment, suppression, ceasefire, escalation); Coupling (deterrence thresholds, spatial threat diffusion, capital flight triggers).
- **Human Capital & Education:** Stocks (attainment distributions, skill proficiency pools, research capacity); Flows (enrollment, graduation, attrition, knowledge transfer, skill depreciation); Coupling (human capital production functions, technological adoption velocity, intergenerational mobility).

**3. System Architecture & Operational Workflow**
- **Phase I: Geospatial Ontology Resolution & Boundary Partitioning**
  Parses polygon; intersects with multi-source geospatial registries; generates hierarchical tessellation; assigns domain-specific priors and spatial adjacency rules per tile.
- **Phase II: Autonomous AI Research & Parameter Extraction**
  Multi-agent LLM/knowledge-graph pipeline executes systematic literature mining, gray literature extraction, and open-data API querying. Extracts empirical distributions, structural archetypes, and coupling coefficients. Attaches epistemic confidence scores via source provenance tracking and cross-validation against domain benchmarks.
- **Phase III: Multi-Modal Data Fusion & State Initialization**
  Harmonizes heterogeneous temporal/spatial frequencies via state-space alignment and Gaussian process co-kriging. Initializes stock vectors \( \mathbf{S}(t_0) \) with uncertainty bounds. Enforces conservation invariants, dimensional homogeneity, and physical/statistical boundary constraints.
- **Phase IV: Causal Discovery & Structural Synthesis**
  Applies PCMCI+/FCI/GES algorithms to longitudinal multi-domain datasets. Infers directed feedback hypergraphs. Resolves algebraic loops via Dulmage–Mendelsohn decomposition and implicit solver insertion. Maps structures to domain-specific SD archetypes.
- **Phase V: Constraint-Aware Equation Generation**
  Symbolic regression with dimensional, conservation, and non-negativity priors produces closed-form flow equations. Embeds cross-domain transfer tensors \( \mathcal{C}_{ijk}(t) \). Enforces stock-flow consistency and prevents structural overparameterization via sparsity regularization.
- **Phase VI: Calibration, Data Assimilation & Uncertainty Partitioning**
  Bayesian hierarchical inference with domain-informed priors. Structural identifiability via Fisher information and profile likelihood. Sequential filtering (EnKF/Particle MCMC) for online state estimation. Explicit aleatory/epistemic variance decomposition \( \sigma^2_{\text{total}} = \sigma^2_{\text{aleatory}} + \sigma^2_{\text{epistemic}} \).
- **Phase VII: Continuous Refinement & Predictive Execution**
  Residual-driven topology adjustment via information criteria (WAIC/AICc) and probabilistic skill scoring. Regime-shift detection (critical slowing down, variance inflation) triggers non-stationary parameterization. Hybrid continuous–discrete solver executes distributed Monte Carlo/Polynomial Chaos ensembles for predictive trajectory generation.

**4. Computational & Algorithmic Infrastructure**
- **Solver Backend:** Adaptive-step stiff ODE/SDE integrators (BDF/Rosenbrock/Euler–Maruyama); discrete-event scheduler for policy/infrastructure regime switches; Jacobian sparsity exploitation for high-dimensional integration.
- **AI/ML Pipeline:** Constraint-guided symbolic regression, causal structure learning, Gaussian process emulators for surrogate modeling, multi-agent knowledge extraction with calibrated confidence scoring.
- **Scalability:** Distributed graph computation, GPU-accelerated uncertainty propagation, dimensional reduction (POD/DMD/SINDy) for tractable high-resolution domain coupling.
- **Interoperability:** FAIR-compliant APIs, FMI/HMA co-simulation standards, geospatial raster/vector exchange, versioned model lineage with cryptographic provenance tracking.

**5. Expected Outputs & Deliverables**
- **Model Artifacts:** Directed hypergraph topology, closed-form flow equations, parameter distributions with uncertainty bounds, conservation/consistency audit logs, structural identifiability reports.
- **Predictive Trajectories:** Probabilistic stock/flow projections with quantile envelopes; scenario matrices for exogenous/endogenous perturbations (policy shifts, resource shocks, conflict escalation, climate forcing).
- **Structural Diagnostics:** Sensitivity indices (Sobol/Morris), dominant feedback loop rankings, structural sloppiness maps, regime-shift early warning signals, coupling pathway dominance tensors.
- **Validation Reports:** Cross-validated probabilistic skill scores (CRPS, logarithmic scoring), residual autocorrelation diagnostics, aleatory/epistemic partitioning metrics, multi-model ensemble variance bounds.
- **Decision Support Interface:** Interactive perturbation simulator, policy/infrastructure shock injector, value-of-information calculator, robust optimization wrapper (chance-constrained/min-max regret/real options).

**6. Performance & Validation Metrics**
- Predictive calibration: PIT uniformity, CRPS < domain-specific baseline, logarithmic scoring optimization.
- Structural robustness: Multi-model ensemble variance < 15% for critical stock trajectories under 95% confidence.
- Computational efficiency: Ensemble generation \( < T_{\text{wall}} \) for policy-relevant horizons (10–50 yr) with \( N \geq 10^4 \) trajectories.
- Epistemic accountability: Full provenance traceability, confidence-scored data lineage, explicit normative assumption registry, bias-audited training corpora.

**7. Operational Constraints & Governance**
- Non-stationarity handling: Time-varying coupling weights, structural mutation tracking, regime-switching formalisms.
- Ethical/Normative boundaries: Policy-neutral baseline generation, explicit value-assumption encoding, algorithmic bias mitigation.
- Tractability limits: Curse of dimensionality mitigated via sparse identification, manifold learning, hierarchical aggregation.
- Validation epistemology: Mandatory multi-model ensemble inference, explicit equifinality acknowledgment, structural confidence interval reporting.

This specification provides the complete ontological, algorithmic, and computational blueprint required for engineering an autonomous geographic SD synthesis engine with research-grade predictive fidelity. All components are formally constrained, computationally tractable, and explicitly validated against stochastic and structural uncertainty regimes.