# SCI Peer Review Report

**Journal:** International Journal of Geographical Information Science / IEEE TGRS (Targeted)
**Manuscript Title:** A Three-Angle Framework for Spatio-Temporal Causal Inference: Integrating Statistical Methods, LLM Reasoning, and World Model Simulation
**Authors:** Ning Zhou and Xiang Jing
**Date:** March 27, 2026
**Recommendation:** **Major Revision**

---

## 1. Overall Evaluation
This paper presents an ambitious and forward-thinking "Three-Angle" framework to address fundamental challenges in geographic causal inference: spatial confounding, limited experimental control, and complex multi-scale mechanisms. By unifying statistical rigor (Angle A), large language model (LLM) reasoning (Angle B), and world model simulation (Angle C), the authors provide a comprehensive closed-loop methodology for spatio-temporal analysis. The manuscript is well-structured and technically sound, representing a significant methodological advance in the field of AI-driven GIS.

## 2. Innovation Evaluation [High]
- **Integration of Paradigms:** The systematic coupling of knowledge-driven LLMs with data-driven statistical methods and simulation-driven world models is highly novel. This triad addresses the "What," "Why," and "What-if" of causal analysis simultaneously.
- **Learned Spatial Confounders:** The use of 64-dimensional GeoFM (AlphaEarth) embeddings as proxies for unmeasured environmental confounders is a paradigm shift from traditional fixed-effect or distance-based controls. It allows for capturing complex, non-linear environmental context that traditional covariates often miss.
- **Bayesian Simulation Calibration:** The proposed mechanism (Eq. 9) that uses empirical ATT estimates to rescale world model scenario encodings is a brilliant strategy to ground generative simulations in statistical reality.

## 3. Practicality and Impact [Medium to High]
- **Engineering Completeness:** The inclusion of 3,245 lines of production code and extensive testing (82 functions) demonstrates that the framework is ready for operational deployment.
- **Policy Relevance:** The spillover analysis and counterfactual comparison tools in Angle C are directly applicable to urban planning and environmental policy evaluation (e.g., assessing the regional impact of a local greening project).
- **Tool Accessibility:** The modular design of 14 tool functions makes the framework adaptable to various geographic domains.

## 4. Reference Integrity Check
- **Team Gemini (2024):** Correctly cited (arXiv:2312.11805) as the technical foundation for reasoning.
- **Brown et al. (2025):** The citation for AlphaEarth (arXiv:2507.22291) is timely and accurately reflects state-of-the-art foundation models.
- **Zhou and Jing (2026):** Self-citation for the World Model is appropriate given the current submission context, provided the model details are sufficiently self-contained here.
- **Foundational Texts:** Pearl (2009) and Sugihara (2012) are correctly integrated into the theoretical framework.

## 5. Specific Comments and Required Revisions

### Statistical Rigor
- **High-Dimensional Confounding:** Using 64-dimensional embeddings as confounders raises concerns about multicollinearity and overfitting, especially in Scenarios with small sample sizes (e.g., n=200). The authors should discuss whether regularization (e.g., Lasso) or dimensionality reduction was employed before matching.
- **GPS Assumptions:** Equation 3 assumes normally distributed residuals for GPS estimation. Many geographic variables follow long-tailed distributions; the authors should justify this choice or discuss non-parametric alternatives.

### Experimental Validation
- **CRITICAL WEAKNESS:** The validation is currently limited to six synthetic datasets. While these demonstrate the framework's internal consistency, SCI-tier journals typically require at least one **real-world case study** (e.g., real estate price changes following a specific urban park construction) to prove robustness against real-world noise and unobserved selection bias.

### LLM Stability
- **Reproducibility of Angle B:** LLM outputs are inherently stochastic. The authors should describe the prompt engineering techniques (e.g., temperature settings, few-shot templates, or self-consistency checks) used to ensure that the generated DAGs are stable and theoretically sound across multiple runs.

### Mathematical Consistency
- **Notation Alignment:** In Section 6.1, $s_{intervention}$ is used, while Section 7 mentions scenario IDs (0–4). A mapping table or clearer definition would improve readability.

---

## Final Summary
This is a high-quality manuscript that pushes the boundaries of causal inference in GIS. If the authors can address the requirement for a real-world case study and clarify the statistical handling of high-dimensional embeddings, this paper is likely to achieve high citation impact and set a new standard for AI-integrated geographic research.
