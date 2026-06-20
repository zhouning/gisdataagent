#!/usr/bin/env python3
"""Prepare TWM authoritative references for Zotero import.

The source list lives in docs/twm-authoritative-references.md.  This script
normalizes that table into machine-readable metadata, reuses known local BibTeX
entries where available, writes Zotero-importable RIS/BibTeX sidecars, and
downloads legally accessible open PDFs when a stable public URL is known.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import quote


REPO_ROOT = Path(__file__).resolve().parents[1]
SOURCE_MD = REPO_ROOT / "docs" / "twm-authoritative-references.md"
OUTPUT_DIR = REPO_ROOT / "docs" / "references" / "twm-authoritative"
ZOTERO_COLLECTION_DIR = Path("/Users/zhouning/Zotero/storage/TWM_AUTHORITATIVE_REFERENCES")

LOCAL_BIB_PATHS = [
    Path("/Users/zhouning/arcgis-farmland-mpc/paper/references_v6.bib"),
    Path("/Users/zhouning/arcgis-farmland-mpc/paper/references_v6_codex.bib"),
    Path("/Users/zhouning/paper10-geojepa-mpc-farmland-layout/references/paper10_verified_references_2026-06-09.bib"),
    Path("/Users/zhouning/paper10-geojepa-mpc-farmland-layout/references/paper10_local_sources_2026-06-09.bib"),
    Path("/Users/zhouning/alphaearth-training-system/paper12/references.bib"),
    Path("/Users/zhouning/alphaearth-training-system/submission/paper12_isprs_jprs_20260606/02_latex_source/references.bib"),
    Path("/Users/zhouning/farmland-drl-optimization/manuscript/references.bib"),
]


# Curated metadata for the items in docs/twm-authoritative-references.md.
# Local BibTeX is still preferred when the title/key match is reliable.  This
# table fills titles, identifiers, and legal open-PDF URLs for the remaining
# items without depending on brittle live search results.
CURATED: dict[str, dict[str, Any]] = {
    "sutton1991dyna": {
        "entry_type": "article",
        "title": "Dyna, an integrated architecture for learning, planning, and reacting",
        "authors": ["Sutton, Richard S."],
        "year": "1991",
        "venue": "ACM SIGART Bulletin",
        "volume": "2",
        "number": "4",
        "pages": "160--163",
        "doi": "10.1145/122344.122377",
        "best_url": "https://doi.org/10.1145/122344.122377",
        "pdf_url": "http://incompleteideas.net/papers/sutton-91-dyna.pdf",
        "access_status": "open_pdf_known",
    },
    "ha2018worldmodels": {
        "entry_type": "inproceedings",
        "title": "Recurrent World Models Facilitate Policy Evolution",
        "authors": ["Ha, David", "Schmidhuber, Jurgen"],
        "year": "2018",
        "venue": "Advances in Neural Information Processing Systems",
        "volume": "31",
        "best_url": "https://worldmodels.github.io/",
        "pdf_url": "https://worldmodels.github.io/assets/world_models.pdf",
        "access_status": "open_pdf_known",
    },
    "hafner2019planet": {
        "entry_type": "inproceedings",
        "title": "Learning Latent Dynamics for Planning from Pixels",
        "authors": [
            "Hafner, Danijar",
            "Lillicrap, Timothy",
            "Fischer, Ian",
            "Villegas, Ruben",
            "Ha, David",
            "Lee, Honglak",
            "Davidson, James",
        ],
        "year": "2019",
        "venue": "Proceedings of the 36th International Conference on Machine Learning",
        "volume": "97",
        "pages": "2555--2565",
        "best_url": "https://proceedings.mlr.press/v97/hafner19a.html",
        "pdf_url": "https://proceedings.mlr.press/v97/hafner19a/hafner19a.pdf",
        "access_status": "open_pdf_known",
    },
    "hafner2020dreamer": {
        "entry_type": "inproceedings",
        "title": "Dream to Control: Learning Behaviors by Latent Imagination",
        "authors": ["Hafner, Danijar", "Lillicrap, Timothy", "Ba, Jimmy", "Norouzi, Mohammad"],
        "year": "2020",
        "venue": "International Conference on Learning Representations",
        "best_url": "https://openreview.net/forum?id=S1lOTC4tDS",
        "pdf_url": "https://openreview.net/pdf?id=S1lOTC4tDS",
        "access_status": "open_pdf_known",
    },
    "schrittwieser2020muzero": {
        "entry_type": "article",
        "title": "Mastering Atari, Go, chess and shogi by planning with a learned model",
        "authors": [
            "Schrittwieser, Julian",
            "Antonoglou, Ioannis",
            "Hubert, Thomas",
            "Simonyan, Karen",
            "Sifre, Laurent",
            "Schmitt, Simon",
            "Guez, Arthur",
            "Lockhart, Edward",
            "Hassabis, Demis",
            "Graepel, Thore",
            "Lillicrap, Timothy",
            "Silver, David",
        ],
        "year": "2020",
        "venue": "Nature",
        "volume": "588",
        "number": "7839",
        "pages": "604--609",
        "doi": "10.1038/s41586-020-03051-4",
        "best_url": "https://doi.org/10.1038/s41586-020-03051-4",
        "access_status": "metadata_only_paywalled_or_no_stable_open_pdf",
    },
    "chua2018pets": {
        "entry_type": "inproceedings",
        "title": "Deep reinforcement learning in a handful of trials using probabilistic dynamics models",
        "authors": ["Chua, Kurtland", "Calandra, Roberto", "McAllister, Rowan", "Levine, Sergey"],
        "year": "2018",
        "venue": "Advances in Neural Information Processing Systems",
        "volume": "31",
        "best_url": "https://papers.nips.cc/paper/2018/hash/3de568f8597b94bda53149c7d7f5958c-Abstract.html",
        "pdf_url": "https://proceedings.neurips.cc/paper_files/paper/2018/file/3de568f8597b94bda53149c7d7f5958c-Paper.pdf",
        "access_status": "open_pdf_known",
    },
    "janner2019mbpo": {
        "entry_type": "inproceedings",
        "title": "When to trust your model: Model-based policy optimization",
        "authors": ["Janner, Michael", "Fu, Justin", "Zhang, Marvin", "Levine, Sergey"],
        "year": "2019",
        "venue": "Advances in Neural Information Processing Systems",
        "volume": "32",
        "best_url": "https://papers.nips.cc/paper/2019/hash/5faf461eff3099671ad63c6f3f094f7f-Abstract.html",
        "pdf_url": "https://proceedings.neurips.cc/paper_files/paper/2019/file/5faf461eff3099671ad63c6f3f094f7f-Paper.pdf",
        "access_status": "open_pdf_known",
    },
    "hansen2022tdmpc": {
        "entry_type": "inproceedings",
        "title": "Temporal Difference Learning for Model Predictive Control",
        "authors": ["Hansen, Nicklas", "Wang, Xiaolong", "Su, Hao"],
        "year": "2022",
        "venue": "International Conference on Machine Learning",
        "best_url": "https://proceedings.mlr.press/v162/hansen22a.html",
        "pdf_url": "https://proceedings.mlr.press/v162/hansen22a/hansen22a.pdf",
        "access_status": "open_pdf_known",
        "note": "Represents TD-MPC in the source row 'TD-MPC / TD-MPC2'.",
    },
    "hansen2024tdmpc2": {
        "entry_type": "inproceedings",
        "title": "TD-MPC2: Scalable, robust world models for continuous control",
        "authors": ["Hansen, Nicklas", "Su, Hao", "Wang, Xiaolong"],
        "year": "2024",
        "venue": "International Conference on Learning Representations",
        "best_url": "https://openreview.net/forum?id=Oxh5CstDJU",
        "pdf_url": "https://openreview.net/pdf?id=Oxh5CstDJU",
        "access_status": "open_pdf_known",
        "note": "Represents TD-MPC2 in the source row 'TD-MPC / TD-MPC2'.",
    },
    "camacho2013mpc": {
        "entry_type": "book",
        "title": "Model Predictive Control",
        "authors": ["Camacho, Eduardo F.", "Bordons, Carlos"],
        "year": "2013",
        "venue": "Springer",
        "publisher": "Springer",
        "doi": "10.1007/978-0-85729-398-5",
        "best_url": "https://doi.org/10.1007/978-0-85729-398-5",
        "access_status": "metadata_only_book",
    },
    "rawlings2017mpc": {
        "entry_type": "book",
        "title": "Model Predictive Control: Theory, Computation, and Design",
        "authors": ["Rawlings, James B.", "Mayne, David Q.", "Diehl, Moritz M."],
        "year": "2017",
        "venue": "Nob Hill Publishing",
        "publisher": "Nob Hill Publishing",
        "best_url": "https://sites.engineering.ucsb.edu/~jbraw/mpc/",
        "access_status": "metadata_only_book",
    },
    "williams2017mppi": {
        "entry_type": "article",
        "title": "Model predictive path integral control: From theory to parallel computation",
        "authors": [
            "Williams, Grady",
            "Drews, Paul",
            "Goldfain, Brian",
            "Rehg, James M.",
            "Theodorou, Evangelos A.",
        ],
        "year": "2017",
        "venue": "Journal of Guidance, Control, and Dynamics",
        "volume": "40",
        "number": "2",
        "pages": "344--357",
        "doi": "10.2514/1.G001921",
        "best_url": "https://doi.org/10.2514/1.G001921",
        "access_status": "metadata_only_paywalled_or_no_stable_open_pdf",
    },
    "amos2017optnet": {
        "entry_type": "inproceedings",
        "title": "OptNet: Differentiable Optimization as a Layer in Neural Networks",
        "authors": ["Amos, Brandon", "Kolter, J. Zico"],
        "year": "2017",
        "venue": "Proceedings of the 34th International Conference on Machine Learning",
        "volume": "70",
        "pages": "136--145",
        "best_url": "https://proceedings.mlr.press/v70/amos17a.html",
        "pdf_url": "https://proceedings.mlr.press/v70/amos17a/amos17a.pdf",
        "access_status": "open_pdf_known",
    },
    "rubin1974causal": {
        "entry_type": "article",
        "title": "Estimating causal effects of treatments in randomized and nonrandomized studies",
        "authors": ["Rubin, Donald B."],
        "year": "1974",
        "venue": "Journal of Educational Psychology",
        "volume": "66",
        "number": "5",
        "pages": "688--701",
        "doi": "10.1037/h0037350",
        "best_url": "https://doi.org/10.1037/h0037350",
        "access_status": "metadata_only_paywalled_or_no_stable_open_pdf",
    },
    "rosenbaum1983propensity": {
        "entry_type": "article",
        "title": "The central role of the propensity score in observational studies for causal effects",
        "authors": ["Rosenbaum, Paul R.", "Rubin, Donald B."],
        "year": "1983",
        "venue": "Biometrika",
        "volume": "70",
        "number": "1",
        "pages": "41--55",
        "doi": "10.1093/biomet/70.1.41",
        "best_url": "https://doi.org/10.1093/biomet/70.1.41",
        "access_status": "metadata_only_paywalled_or_no_stable_open_pdf",
    },
    "pearl2009causality": {
        "entry_type": "book",
        "title": "Causality: Models, Reasoning, and Inference",
        "authors": ["Pearl, Judea"],
        "year": "2009",
        "venue": "Cambridge University Press",
        "publisher": "Cambridge University Press",
        "best_url": "https://www.cambridge.org/core/books/causality/3A9714D7B07946B52BE2D9F6FE51A5B1",
        "access_status": "metadata_only_book",
    },
    "imbens2015causal": {
        "entry_type": "book",
        "title": "Causal Inference for Statistics, Social, and Biomedical Sciences: An Introduction",
        "authors": ["Imbens, Guido W.", "Rubin, Donald B."],
        "year": "2015",
        "venue": "Cambridge University Press",
        "publisher": "Cambridge University Press",
        "doi": "10.1017/CBO9781139025751",
        "best_url": "https://doi.org/10.1017/CBO9781139025751",
        "access_status": "metadata_only_book",
    },
    "athey2016recursive": {
        "entry_type": "article",
        "title": "Recursive partitioning for heterogeneous causal effects",
        "authors": ["Athey, Susan", "Imbens, Guido"],
        "year": "2016",
        "venue": "Proceedings of the National Academy of Sciences",
        "volume": "113",
        "number": "27",
        "pages": "7353--7360",
        "doi": "10.1073/pnas.1510489113",
        "best_url": "https://doi.org/10.1073/pnas.1510489113",
        "pdf_url": "https://www.pnas.org/doi/pdf/10.1073/pnas.1510489113",
        "access_status": "open_pdf_known",
    },
    "wager2018causalforest": {
        "entry_type": "article",
        "title": "Estimation and inference of heterogeneous treatment effects using random forests",
        "authors": ["Wager, Stefan", "Athey, Susan"],
        "year": "2018",
        "venue": "Journal of the American Statistical Association",
        "volume": "113",
        "number": "523",
        "pages": "1228--1242",
        "doi": "10.1080/01621459.2017.1319839",
        "best_url": "https://doi.org/10.1080/01621459.2017.1319839",
        "pdf_url": "https://arxiv.org/pdf/1510.04342",
        "arxiv": "1510.04342",
        "access_status": "open_pdf_known",
    },
    "chernozhukov2018doubleml": {
        "entry_type": "article",
        "title": "Double/debiased machine learning for treatment and structural parameters",
        "authors": [
            "Chernozhukov, Victor",
            "Chetverikov, Denis",
            "Demirer, Mert",
            "Duflo, Esther",
            "Hansen, Christian",
            "Newey, Whitney",
            "Robins, James",
        ],
        "year": "2018",
        "venue": "The Econometrics Journal",
        "volume": "21",
        "number": "1",
        "pages": "C1--C68",
        "doi": "10.1111/ectj.12097",
        "best_url": "https://doi.org/10.1111/ectj.12097",
        "pdf_url": "https://arxiv.org/pdf/1608.00060",
        "arxiv": "1608.00060",
        "access_status": "open_pdf_known",
    },
    "battaglia2018graphnetworks": {
        "entry_type": "article",
        "title": "Relational inductive biases, deep learning, and graph networks",
        "authors": [
            "Battaglia, Peter W.",
            "Hamrick, Jessica B.",
            "Bapst, Victor",
            "Sanchez-Gonzalez, Alvaro",
            "Zambaldi, Vinicius",
            "Malinowski, Mateusz",
            "Tacchetti, Andrea",
            "Raposo, David",
            "Santoro, Adam",
            "Faulkner, Ryan",
            "Gulcehre, Caglar",
            "Song, Francis",
            "Ballard, Andrew",
            "Gilmer, Justin",
            "Dahl, George",
            "Vaswani, Ashish",
            "Allen, Kelsey",
            "Nash, Charles",
            "Langston, Victoria",
            "Dyer, Chris",
            "Heess, Nicolas",
            "Wierstra, Daan",
            "Kohli, Pushmeet",
            "Botvinick, Matthew",
            "Vinyals, Oriol",
            "Li, Yujia",
            "Pascanu, Razvan",
        ],
        "year": "2018",
        "venue": "arXiv preprint arXiv:1806.01261",
        "arxiv": "1806.01261",
        "best_url": "https://arxiv.org/abs/1806.01261",
        "pdf_url": "https://arxiv.org/pdf/1806.01261",
        "access_status": "open_pdf_known",
    },
    "kipf2017gcn": {
        "entry_type": "inproceedings",
        "title": "Semi-Supervised Classification with Graph Convolutional Networks",
        "authors": ["Kipf, Thomas N.", "Welling, Max"],
        "year": "2017",
        "venue": "International Conference on Learning Representations",
        "arxiv": "1609.02907",
        "best_url": "https://openreview.net/forum?id=SJU4ayYgl",
        "pdf_url": "https://openreview.net/pdf?id=SJU4ayYgl",
        "access_status": "open_pdf_known",
    },
    "velickovic2018gat": {
        "entry_type": "inproceedings",
        "title": "Graph Attention Networks",
        "authors": [
            "Velickovic, Petar",
            "Cucurull, Guillem",
            "Casanova, Arantxa",
            "Romero, Adriana",
            "Lio, Pietro",
            "Bengio, Yoshua",
        ],
        "year": "2018",
        "venue": "International Conference on Learning Representations",
        "arxiv": "1710.10903",
        "best_url": "https://openreview.net/forum?id=rJXMpikCZ",
        "pdf_url": "https://openreview.net/pdf?id=rJXMpikCZ",
        "access_status": "open_pdf_known",
    },
    "bronstein2021geometric": {
        "entry_type": "article",
        "title": "Geometric Deep Learning: Grids, Groups, Graphs, Geodesics, and Gauges",
        "authors": [
            "Bronstein, Michael M.",
            "Bruna, Joan",
            "Cohen, Taco",
            "Velickovic, Petar",
        ],
        "year": "2021",
        "venue": "arXiv preprint arXiv:2104.13478",
        "arxiv": "2104.13478",
        "best_url": "https://arxiv.org/abs/2104.13478",
        "pdf_url": "https://arxiv.org/pdf/2104.13478",
        "access_status": "open_pdf_known",
    },
    "sutton1999options": {
        "entry_type": "article",
        "title": "Between MDPs and semi-MDPs: A framework for temporal abstraction in reinforcement learning",
        "authors": ["Sutton, Richard S.", "Precup, Doina", "Singh, Satinder"],
        "year": "1999",
        "venue": "Artificial Intelligence",
        "volume": "112",
        "number": "1-2",
        "pages": "181--211",
        "doi": "10.1016/S0004-3702(99)00052-1",
        "best_url": "https://doi.org/10.1016/S0004-3702(99)00052-1",
        "access_status": "metadata_only_paywalled_or_no_stable_open_pdf",
    },
    "dietterich2000maxq": {
        "entry_type": "article",
        "title": "Hierarchical reinforcement learning with the MAXQ value function decomposition",
        "authors": ["Dietterich, Thomas G."],
        "year": "2000",
        "venue": "Journal of Artificial Intelligence Research",
        "volume": "13",
        "pages": "227--303",
        "doi": "10.1613/jair.639",
        "best_url": "https://doi.org/10.1613/jair.639",
        "pdf_url": "https://www.jair.org/index.php/jair/article/download/10266/24463",
        "access_status": "open_pdf_known",
    },
    "bacon2017optioncritic": {
        "entry_type": "inproceedings",
        "title": "The Option-Critic Architecture",
        "authors": ["Bacon, Pierre-Luc", "Harb, Jean", "Precup, Doina"],
        "year": "2017",
        "venue": "Proceedings of the AAAI Conference on Artificial Intelligence",
        "volume": "31",
        "number": "1",
        "best_url": "https://ojs.aaai.org/index.php/AAAI/article/view/10916",
        "pdf_url": "https://ojs.aaai.org/index.php/AAAI/article/download/10916/10775",
        "access_status": "open_pdf_known",
    },
    "lowe2017maddpg": {
        "entry_type": "inproceedings",
        "title": "Multi-Agent Actor-Critic for Mixed Cooperative-Competitive Environments",
        "authors": [
            "Lowe, Ryan",
            "Wu, Yi",
            "Tamar, Aviv",
            "Harb, Jean",
            "Abbeel, Pieter",
            "Mordatch, Igor",
        ],
        "year": "2017",
        "venue": "Advances in Neural Information Processing Systems",
        "volume": "30",
        "arxiv": "1706.02275",
        "best_url": "https://arxiv.org/abs/1706.02275",
        "pdf_url": "https://arxiv.org/pdf/1706.02275",
        "access_status": "open_pdf_known",
    },
    "rashid2018qmix": {
        "entry_type": "inproceedings",
        "title": "QMIX: Monotonic Value Function Factorisation for Deep Multi-Agent Reinforcement Learning",
        "authors": [
            "Rashid, Tabish",
            "Samvelyan, Mikayel",
            "Schroeder, Christian",
            "Farquhar, Gregory",
            "Foerster, Jakob",
            "Whiteson, Shimon",
        ],
        "year": "2018",
        "venue": "Proceedings of the 35th International Conference on Machine Learning",
        "volume": "80",
        "pages": "4295--4304",
        "best_url": "https://proceedings.mlr.press/v80/rashid18a.html",
        "pdf_url": "https://proceedings.mlr.press/v80/rashid18a/rashid18a.pdf",
        "access_status": "open_pdf_known",
    },
    "yu2022mappo": {
        "entry_type": "article",
        "title": "The Surprising Effectiveness of PPO in Cooperative Multi-Agent Games",
        "authors": [
            "Yu, Chao",
            "Velu, Akash",
            "Vinitsky, Eugene",
            "Gao, Yu",
            "Wang, Yu",
            "Bayen, Alexandre",
            "Wu, Yi",
        ],
        "year": "2022",
        "venue": "Advances in Neural Information Processing Systems",
        "volume": "35",
        "arxiv": "2103.01955",
        "best_url": "https://arxiv.org/abs/2103.01955",
        "pdf_url": "https://arxiv.org/pdf/2103.01955",
        "access_status": "open_pdf_known",
    },
    "zhang2021marlselective": {
        "entry_type": "article",
        "title": "Multi-Agent Reinforcement Learning: A Selective Overview of Theories and Algorithms",
        "authors": [
            "Zhang, Kaiqing",
            "Yang, Zhuoran",
            "Basar, Tamer",
        ],
        "year": "2021",
        "venue": "Handbook of Reinforcement Learning and Control",
        "pages": "321--384",
        "doi": "10.1007/978-3-030-60990-0_12",
        "best_url": "https://doi.org/10.1007/978-3-030-60990-0_12",
        "pdf_url": "https://arxiv.org/pdf/1911.10635",
        "arxiv": "1911.10635",
        "access_status": "open_pdf_known",
    },
    "he2022mae": {
        "entry_type": "inproceedings",
        "title": "Masked Autoencoders Are Scalable Vision Learners",
        "authors": ["He, Kaiming", "Chen, Xinlei", "Xie, Saining", "Li, Yanghao", "Dollar, Piotr", "Girshick, Ross"],
        "year": "2022",
        "venue": "Proceedings of the IEEE/CVF Conference on Computer Vision and Pattern Recognition",
        "pages": "16000--16009",
        "best_url": "https://openaccess.thecvf.com/content/CVPR2022/html/He_Masked_Autoencoders_Are_Scalable_Vision_Learners_CVPR_2022_paper.html",
        "pdf_url": "https://openaccess.thecvf.com/content/CVPR2022/papers/He_Masked_Autoencoders_Are_Scalable_Vision_Learners_CVPR_2022_paper.pdf",
        "access_status": "open_pdf_known",
    },
    "cong2022satmae": {
        "entry_type": "inproceedings",
        "title": "SatMAE: Pre-training Transformers for Temporal and Multi-Spectral Satellite Imagery",
        "authors": [
            "Cong, Yezhen",
            "Khanna, Samar",
            "Meng, Chenlin",
            "Liu, Patrick",
            "Rozi, Erik",
            "He, Yutong",
            "Burke, Marshall",
            "Lobell, David B.",
            "Ermon, Stefano",
        ],
        "year": "2022",
        "venue": "Advances in Neural Information Processing Systems",
        "volume": "35",
        "arxiv": "2207.08051",
        "best_url": "https://arxiv.org/abs/2207.08051",
        "pdf_url": "https://arxiv.org/pdf/2207.08051",
        "access_status": "open_pdf_known",
    },
    "jakubik2023prithvi": {
        "entry_type": "article",
        "title": "Foundation Models for Generalist Geospatial Artificial Intelligence",
        "authors": [
            "Jakubik, Johannes",
            "Roy, Sujit",
            "Phillips, C. E.",
            "Fraccaro, Paolo",
            "Godwin, Denys",
            "Zadrozny, Bianca",
            "Szwarcman, Daniela",
            "Gomes, Carlos",
            "Nyirjesy, Gabriel",
            "Edwards, Blair",
        ],
        "year": "2023",
        "venue": "arXiv preprint arXiv:2310.18660",
        "arxiv": "2310.18660",
        "best_url": "https://arxiv.org/abs/2310.18660",
        "pdf_url": "https://arxiv.org/pdf/2310.18660",
        "access_status": "open_pdf_known",
    },
    "reed2023scalemae": {
        "entry_type": "inproceedings",
        "title": "Scale-MAE: A Scale-Aware Masked Autoencoder for Multiscale Geospatial Representation Learning",
        "authors": [
            "Reed, Colorado J.",
            "Gupta, Ritwik",
            "Li, Shufan",
            "Brockman, Sarah",
            "Funk, Christopher",
            "Clipp, Brian",
            "Keutzer, Kurt",
            "Candido, Salvatore",
            "Uyttendaele, Matt",
            "Darrell, Trevor",
        ],
        "year": "2023",
        "venue": "Proceedings of the IEEE/CVF International Conference on Computer Vision",
        "best_url": "https://openaccess.thecvf.com/content/ICCV2023/html/Reed_Scale-MAE_A_Scale-Aware_Masked_Autoencoder_for_Multiscale_Geospatial_Representation_Learning_ICCV_2023_paper.html",
        "pdf_url": "https://openaccess.thecvf.com/content/ICCV2023/papers/Reed_Scale-MAE_A_Scale-Aware_Masked_Autoencoder_for_Multiscale_Geospatial_Representation_Learning_ICCV_2023_paper.pdf",
        "access_status": "open_pdf_known",
    },
    "hong2024spectralgpt": {
        "entry_type": "article",
        "title": "SpectralGPT: Spectral Remote Sensing Foundation Model",
        "authors": [
            "Hong, Danfeng",
            "Zhang, Bing",
            "Li, Xuyang",
            "Li, Yuxuan",
            "Li, Chenyu",
            "Yao, Jing",
            "Yokoya, Naoto",
            "Li, Hao",
            "Ghamisi, Pedram",
            "Jia, Xiuping",
        ],
        "year": "2024",
        "venue": "IEEE Transactions on Pattern Analysis and Machine Intelligence",
        "doi": "10.1109/TPAMI.2024.3362475",
        "best_url": "https://doi.org/10.1109/TPAMI.2024.3362475",
        "pdf_url": "https://arxiv.org/pdf/2311.07113",
        "arxiv": "2311.07113",
        "access_status": "open_pdf_known",
    },
    "assran2023ijepa": {
        "entry_type": "inproceedings",
        "title": "Self-Supervised Learning from Images with a Joint-Embedding Predictive Architecture",
        "authors": [
            "Assran, Mahmoud",
            "Duval, Quentin",
            "Misra, Ishan",
            "Bojanowski, Piotr",
            "Vincent, Pascal",
            "Rabbat, Michael",
            "LeCun, Yann",
            "Ballas, Nicolas",
        ],
        "year": "2023",
        "venue": "Proceedings of the IEEE/CVF Conference on Computer Vision and Pattern Recognition",
        "pages": "15619--15629",
        "doi": "10.1109/CVPR52729.2023.01499",
        "best_url": "https://openaccess.thecvf.com/content/CVPR2023/html/Assran_Self-Supervised_Learning_From_Images_With_a_Joint-Embedding_Predictive_Architecture_CVPR_2023_paper.html",
        "pdf_url": "https://openaccess.thecvf.com/content/CVPR2023/papers/Assran_Self-Supervised_Learning_From_Images_With_a_Joint-Embedding_Predictive_Architecture_CVPR_2023_paper.pdf",
        "access_status": "open_pdf_known",
    },
    "bardes2024vjepa": {
        "entry_type": "inproceedings",
        "title": "Revisiting Feature Prediction for Learning Visual Representations from Video",
        "authors": [
            "Bardes, Adrien",
            "Garrido, Quentin",
            "Ponce, Jean",
            "Chen, Xinlei",
            "Rabbat, Michael",
            "LeCun, Yann",
            "Assran, Mahmoud",
            "Ballas, Nicolas",
        ],
        "year": "2024",
        "venue": "arXiv preprint arXiv:2404.08471",
        "arxiv": "2404.08471",
        "best_url": "https://arxiv.org/abs/2404.08471",
        "pdf_url": "https://arxiv.org/pdf/2404.08471",
        "access_status": "open_pdf_known",
    },
    "guo2017calibration": {
        "entry_type": "inproceedings",
        "title": "On Calibration of Modern Neural Networks",
        "authors": ["Guo, Chuan", "Pleiss, Geoff", "Sun, Yu", "Weinberger, Kilian Q."],
        "year": "2017",
        "venue": "Proceedings of the 34th International Conference on Machine Learning",
        "volume": "70",
        "pages": "1321--1330",
        "best_url": "https://proceedings.mlr.press/v70/guo17a.html",
        "pdf_url": "https://proceedings.mlr.press/v70/guo17a/guo17a.pdf",
        "access_status": "open_pdf_known",
    },
    "lakshminarayanan2017deepensembles": {
        "entry_type": "inproceedings",
        "title": "Simple and scalable predictive uncertainty estimation using deep ensembles",
        "authors": ["Lakshminarayanan, Balaji", "Pritzel, Alexander", "Blundell, Charles"],
        "year": "2017",
        "venue": "Advances in Neural Information Processing Systems",
        "volume": "30",
        "best_url": "https://papers.nips.cc/paper/2017/hash/9ef2ed4b7fd2c810847ffa5fa85bce38-Abstract.html",
        "pdf_url": "https://proceedings.neurips.cc/paper_files/paper/2017/file/9ef2ed4b7fd2c810847ffa5fa85bce38-Paper.pdf",
        "access_status": "open_pdf_known",
    },
    "ovadia2019uncertaintyshift": {
        "entry_type": "inproceedings",
        "title": "Can You Trust Your Model's Uncertainty? Evaluating Predictive Uncertainty Under Dataset Shift",
        "authors": [
            "Ovadia, Yaniv",
            "Fertig, Emily",
            "Ren, Jie",
            "Nado, Zachary",
            "Sculley, D.",
            "Nowozin, Sebastian",
            "Dillon, Joshua V.",
            "Lakshminarayanan, Balaji",
            "Snoek, Jasper",
        ],
        "year": "2019",
        "venue": "Advances in Neural Information Processing Systems",
        "volume": "32",
        "best_url": "https://papers.nips.cc/paper/2019/hash/8558cb408c1d76621371888657d2eb1d-Abstract.html",
        "pdf_url": "https://proceedings.neurips.cc/paper_files/paper/2019/file/8558cb408c1d76621371888657d2eb1d-Paper.pdf",
        "access_status": "open_pdf_known",
    },
    "angelopoulos2021conformal": {
        "entry_type": "article",
        "title": "A Gentle Introduction to Conformal Prediction and Distribution-Free Uncertainty Quantification",
        "authors": ["Angelopoulos, Anastasios N.", "Bates, Stephen"],
        "year": "2021",
        "venue": "arXiv preprint arXiv:2107.07511",
        "arxiv": "2107.07511",
        "best_url": "https://arxiv.org/abs/2107.07511",
        "pdf_url": "https://arxiv.org/pdf/2107.07511",
        "access_status": "open_pdf_known",
    },
    "geifman2017selective": {
        "entry_type": "article",
        "title": "Selective Classification for Deep Neural Networks",
        "authors": ["Geifman, Yonatan", "El-Yaniv, Ran"],
        "year": "2017",
        "venue": "arXiv preprint arXiv:1705.08500",
        "arxiv": "1705.08500",
        "best_url": "https://arxiv.org/abs/1705.08500",
        "pdf_url": "https://arxiv.org/pdf/1705.08500",
        "access_status": "open_pdf_known",
    },
    "geifman2019selectivenet": {
        "entry_type": "inproceedings",
        "title": "SelectiveNet: A Deep Neural Network with an Integrated Reject Option",
        "authors": ["Geifman, Yonatan", "El-Yaniv, Ran"],
        "year": "2019",
        "venue": "Proceedings of the 36th International Conference on Machine Learning",
        "volume": "97",
        "pages": "2151--2159",
        "best_url": "https://proceedings.mlr.press/v97/geifman19a.html",
        "pdf_url": "https://proceedings.mlr.press/v97/geifman19a/geifman19a.pdf",
        "access_status": "open_pdf_known",
    },
    "mitchell2019modelcards": {
        "entry_type": "inproceedings",
        "title": "Model Cards for Model Reporting",
        "authors": [
            "Mitchell, Margaret",
            "Wu, Simone",
            "Zaldivar, Andrew",
            "Barnes, Parker",
            "Vasserman, Lucy",
            "Hutchinson, Ben",
            "Spitzer, Elena",
            "Raji, Inioluwa Deborah",
            "Gebru, Timnit",
        ],
        "year": "2019",
        "venue": "Proceedings of the Conference on Fairness, Accountability, and Transparency",
        "pages": "220--229",
        "doi": "10.1145/3287560.3287596",
        "best_url": "https://doi.org/10.1145/3287560.3287596",
        "pdf_url": "https://dl.acm.org/doi/pdf/10.1145/3287560.3287596",
        "access_status": "open_pdf_may_require_publisher_access",
    },
    "gebru2021datasheets": {
        "entry_type": "article",
        "title": "Datasheets for Datasets",
        "authors": [
            "Gebru, Timnit",
            "Morgenstern, Jamie",
            "Vecchione, Briana",
            "Vaughan, Jennifer Wortman",
            "Wallach, Hanna",
            "Daume III, Hal",
            "Crawford, Kate",
        ],
        "year": "2021",
        "venue": "Communications of the ACM",
        "volume": "64",
        "number": "12",
        "pages": "86--92",
        "doi": "10.1145/3458723",
        "best_url": "https://doi.org/10.1145/3458723",
        "pdf_url": "https://arxiv.org/pdf/1803.09010",
        "arxiv": "1803.09010",
        "access_status": "open_pdf_known",
    },
    "wilkinson2016fair": {
        "entry_type": "article",
        "title": "The FAIR Guiding Principles for scientific data management and stewardship",
        "authors": [
            "Wilkinson, Mark D.",
            "Dumontier, Michel",
            "Aalbersberg, IJsbrand Jan",
            "Appleton, Gabrielle",
            "Axton, Myles",
            "Baak, Arie",
            "Blomberg, Niklas",
            "Boiten, Jan-Willem",
            "da Silva Santos, Luiz Bonino",
            "Bourne, Philip E.",
        ],
        "year": "2016",
        "venue": "Scientific Data",
        "volume": "3",
        "pages": "160018",
        "doi": "10.1038/sdata.2016.18",
        "best_url": "https://doi.org/10.1038/sdata.2016.18",
        "pdf_url": "https://www.nature.com/articles/sdata201618.pdf",
        "access_status": "open_pdf_known",
    },
    "w3c2013provdm": {
        "entry_type": "misc",
        "title": "PROV-DM: The PROV Data Model",
        "authors": ["Moreau, Luc", "Missier, Paolo"],
        "year": "2013",
        "venue": "W3C Recommendation",
        "best_url": "https://www.w3.org/TR/prov-dm/",
        "access_status": "metadata_only_standard",
    },
    "moreau2011opm": {
        "entry_type": "article",
        "title": "The Open Provenance Model core specification (v1.1)",
        "authors": [
            "Moreau, Luc",
            "Clifford, Ben",
            "Freire, Juliana",
            "Futrelle, Joe",
            "Gil, Yolanda",
            "Groth, Paul",
            "Kwasnikowska, Natalia",
            "Miles, Simon",
            "Missier, Paolo",
            "Myers, Jim",
            "Plale, Beth",
            "Simmhan, Yogesh",
            "Stephan, Eric",
            "Van den Bussche, Jan",
        ],
        "year": "2011",
        "venue": "Future Generation Computer Systems",
        "volume": "27",
        "number": "6",
        "pages": "743--756",
        "doi": "10.1016/j.future.2010.07.005",
        "best_url": "https://doi.org/10.1016/j.future.2010.07.005",
        "access_status": "metadata_only_paywalled_or_no_stable_open_pdf",
    },
    "iso19115": {
        "entry_type": "standard",
        "title": "ISO 19115 Geographic information - Metadata",
        "authors": ["International Organization for Standardization"],
        "year": "2014",
        "venue": "ISO 19115-1:2014",
        "best_url": "https://www.iso.org/standard/53798.html",
        "access_status": "metadata_only_standard",
    },
    "iso19157": {
        "entry_type": "standard",
        "title": "ISO 19157 Geographic information - Data quality",
        "authors": ["International Organization for Standardization"],
        "year": "2013",
        "venue": "ISO 19157:2013",
        "best_url": "https://www.iso.org/standard/32575.html",
        "access_status": "metadata_only_standard",
    },
    "clarke1997sleuth": {
        "entry_type": "article",
        "title": "A self-modifying cellular automaton model of historical urbanization in the San Francisco Bay area",
        "authors": ["Clarke, Keith C.", "Hoppen, Stacy", "Gaydos, Leonard"],
        "year": "1997",
        "venue": "Environment and Planning B: Planning and Design",
        "volume": "24",
        "number": "2",
        "pages": "247--261",
        "doi": "10.1068/b240247",
        "best_url": "https://doi.org/10.1068/b240247",
        "access_status": "metadata_only_paywalled_or_no_stable_open_pdf",
    },
    "verburg2002clues": {
        "entry_type": "article",
        "title": "Modeling the spatial dynamics of regional land use: The CLUE-S model",
        "authors": [
            "Verburg, Peter H.",
            "Soepboer, Welmoed",
            "Veldkamp, A.",
            "Limpiada, R.",
            "Espaldon, V.",
            "Mastura, S. S. A.",
        ],
        "year": "2002",
        "venue": "Environmental Management",
        "volume": "30",
        "number": "3",
        "pages": "391--405",
        "doi": "10.1007/s00267-002-2630-x",
        "best_url": "https://doi.org/10.1007/s00267-002-2630-x",
        "access_status": "metadata_only_paywalled_or_no_stable_open_pdf",
    },
    "liu2017flus": {
        "entry_type": "article",
        "title": "A future land use simulation model (FLUS) for simulating multiple land use scenarios by coupling human and natural effects",
        "authors": ["Liu, Xiaoping", "Liang, Xia", "Li, Xia", "Xu, Xiaocong", "Ou, Jianfeng", "Chen, Yong"],
        "year": "2017",
        "venue": "Landscape and Urban Planning",
        "volume": "168",
        "pages": "94--116",
        "doi": "10.1016/j.landurbplan.2017.09.019",
        "best_url": "https://doi.org/10.1016/j.landurbplan.2017.09.019",
        "access_status": "metadata_only_paywalled_or_no_stable_open_pdf",
    },
    "liang2021plus": {
        "entry_type": "article",
        "title": "Understanding the drivers of sustainable land expansion using a patch-generating land use simulation (PLUS) model: A case study in Wuhan, China",
        "authors": ["Liang, Xia", "Guan, Qingfeng", "Clarke, Keith C.", "Liu, Sai", "Wang, Bing", "Yao, Yong"],
        "year": "2021",
        "venue": "Computers, Environment and Urban Systems",
        "volume": "85",
        "pages": "101569",
        "doi": "10.1016/j.compenvurbsys.2020.101569",
        "best_url": "https://doi.org/10.1016/j.compenvurbsys.2020.101569",
        "access_status": "metadata_only_paywalled_or_no_stable_open_pdf",
    },
}


# Source-row matching.  Some rows in the Markdown use shorthand rather than the
# final citation title, so use explicit mappings instead of relying only on fuzzy
# title matching.
ROW_KEYS = [
    ["sutton1991dyna"],
    ["ha2018worldmodels"],
    ["hafner2019planet"],
    ["hafner2020dreamer"],
    ["schrittwieser2020muzero"],
    ["chua2018pets"],
    ["janner2019mbpo"],
    ["hansen2022tdmpc", "hansen2024tdmpc2"],
    ["camacho2013mpc"],
    ["rawlings2017mpc"],
    ["williams2017mppi"],
    ["amos2017optnet"],
    ["rubin1974causal"],
    ["rosenbaum1983propensity"],
    ["pearl2009causality"],
    ["imbens2015causal"],
    ["athey2016recursive"],
    ["wager2018causalforest"],
    ["chernozhukov2018doubleml"],
    ["battaglia2018graphnetworks"],
    ["kipf2017gcn"],
    ["velickovic2018gat"],
    ["bronstein2021geometric"],
    ["sutton1999options"],
    ["dietterich2000maxq"],
    ["bacon2017optioncritic"],
    ["lowe2017maddpg"],
    ["rashid2018qmix"],
    ["yu2022mappo"],
    ["zhang2021marlselective"],
    ["he2022mae"],
    ["cong2022satmae"],
    ["jakubik2023prithvi"],
    ["reed2023scalemae"],
    ["hong2024spectralgpt"],
    ["assran2023ijepa"],
    ["bardes2024vjepa"],
    ["guo2017calibration"],
    ["lakshminarayanan2017deepensembles"],
    ["ovadia2019uncertaintyshift"],
    ["angelopoulos2021conformal"],
    ["geifman2017selective"],
    ["geifman2019selectivenet"],
    ["mitchell2019modelcards"],
    ["gebru2021datasheets"],
    ["wilkinson2016fair"],
    ["w3c2013provdm"],
    ["moreau2011opm"],
    ["iso19115"],
    ["iso19157"],
    ["clarke1997sleuth"],
    ["verburg2002clues"],
    ["liu2017flus"],
    ["liang2021plus"],
]


@dataclass
class BibEntry:
    key: str
    entry_type: str
    fields: dict[str, str]
    raw: str
    source: str


@dataclass
class WorkRecord:
    source_index: int
    sub_index: int
    source_reference: str
    source_section: str
    checkpoint_core_scope: bool
    key: str
    entry_type: str
    title: str
    authors: list[str]
    year: str
    venue: str
    doi: str = ""
    arxiv: str = ""
    best_url: str = ""
    pdf_url: str = ""
    access_status: str = ""
    publisher: str = ""
    volume: str = ""
    number: str = ""
    pages: str = ""
    note: str = ""
    local_bib_key: str = ""
    local_bib_source: str = ""
    attachment_path: str = ""
    attachment_sha256: str = ""
    download_status: str = "not_attempted"
    download_error: str = ""


def normalize_text(value: str) -> str:
    value = value.lower()
    value = value.replace("{", "").replace("}", "")
    value = re.sub(r"\\[a-zA-Z]+\{([^}]*)\}", r"\1", value)
    value = value.replace("\\&", "&")
    value = re.sub(r"[^a-z0-9]+", " ", value)
    return re.sub(r"\s+", " ", value).strip()


def parse_bibtex_blocks(text: str) -> list[tuple[str, str]]:
    blocks: list[tuple[str, str]] = []
    i = 0
    while i < len(text):
        at = text.find("@", i)
        if at == -1:
            break
        j = at + 1
        while j < len(text) and text[j].isalpha():
            j += 1
        while j < len(text) and text[j].isspace():
            j += 1
        if j >= len(text) or text[j] != "{":
            i = j
            continue
        depth = 0
        k = j
        while k < len(text):
            if text[k] == "{":
                depth += 1
            elif text[k] == "}":
                depth -= 1
                if depth == 0:
                    blocks.append((text[at + 1:j].strip().lower(), text[j + 1:k]))
                    i = k + 1
                    break
            k += 1
        else:
            break
    return blocks


def parse_fields(body: str) -> dict[str, str]:
    fields: dict[str, str] = {}
    i = 0
    while i < len(body):
        while i < len(body) and body[i] in " \t\r\n,":
            i += 1
        match = re.match(r"([A-Za-z][A-Za-z0-9_-]*)\s*=\s*", body[i:])
        if not match:
            next_line = body.find("\n", i)
            if next_line == -1:
                break
            i = next_line + 1
            continue
        field = match.group(1).lower()
        i += match.end()
        if i >= len(body):
            break
        if body[i] == "{":
            depth = 0
            j = i
            while j < len(body):
                if body[j] == "{":
                    depth += 1
                elif body[j] == "}":
                    depth -= 1
                    if depth == 0:
                        fields[field] = re.sub(r"\s+", " ", body[i + 1:j]).strip()
                        i = j + 1
                        break
                j += 1
            else:
                break
        elif body[i] == '"':
            j = i + 1
            escaped = False
            while j < len(body):
                if body[j] == '"' and not escaped:
                    fields[field] = re.sub(r"\s+", " ", body[i + 1:j]).strip()
                    i = j + 1
                    break
                escaped = body[j] == "\\" and not escaped
                if body[j] != "\\":
                    escaped = False
                j += 1
            else:
                break
        else:
            j = i
            while j < len(body) and body[j] not in ",\n":
                j += 1
            fields[field] = body[i:j].strip()
            i = j
    return fields


def load_local_bib_entries() -> dict[str, BibEntry]:
    entries: dict[str, BibEntry] = {}
    for path in LOCAL_BIB_PATHS:
        if not path.exists():
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        for entry_type, block in parse_bibtex_blocks(text):
            if "," not in block:
                continue
            key, body = block.split(",", 1)
            fields = parse_fields(body)
            title = fields.get("title")
            if not title:
                continue
            raw = f"@{entry_type}{{{block}}}"
            entries.setdefault(
                normalize_text(title),
                BibEntry(key=key.strip(), entry_type=entry_type, fields=fields, raw=raw, source=str(path)),
            )
    return entries


def extract_source_rows(source_path: Path) -> list[tuple[str, str]]:
    rows: list[tuple[str, str]] = []
    section = ""
    for line in source_path.read_text(encoding="utf-8").splitlines():
        if line.startswith("## "):
            section = line.strip("# ").strip()
            continue
        if not line.startswith("|"):
            continue
        parts = [part.strip() for part in line.strip("|").split("|")]
        if len(parts) < 3:
            continue
        first = parts[0]
        if first in {"推荐引用", "---", ""}:
            continue
        rows.append((section, first))
    return rows


def bib_author_to_list(value: str) -> list[str]:
    if not value:
        return []
    return [re.sub(r"\s+", " ", part).strip() for part in value.split(" and ") if part.strip()]


def build_records(rows: list[tuple[str, str]], local_entries: dict[str, BibEntry]) -> list[WorkRecord]:
    if len(rows) != len(ROW_KEYS):
        raise RuntimeError(f"Expected {len(ROW_KEYS)} source rows, got {len(rows)}")

    records: list[WorkRecord] = []
    for row_index, ((section, source_reference), keys) in enumerate(zip(rows, ROW_KEYS), start=1):
        for sub_index, key in enumerate(keys, start=1):
            data = CURATED[key].copy()
            local = local_entries.get(normalize_text(data["title"]))
            if local:
                fields = local.fields
                data.setdefault("entry_type", local.entry_type)
                data["title"] = strip_bib_braces(fields.get("title", data["title"]))
                data["authors"] = bib_author_to_list(fields.get("author", "")) or data.get("authors", [])
                data["year"] = fields.get("year", data.get("year", ""))
                data["venue"] = fields.get("journal") or fields.get("booktitle") or data.get("venue", "")
                for src_field, dst_field in [
                    ("doi", "doi"),
                    ("url", "best_url"),
                    ("eprint", "arxiv"),
                    ("volume", "volume"),
                    ("number", "number"),
                    ("pages", "pages"),
                    ("publisher", "publisher"),
                ]:
                    if fields.get(src_field) and not data.get(dst_field):
                        data[dst_field] = fields[src_field]
            record = WorkRecord(
                source_index=row_index,
                sub_index=sub_index,
                source_reference=source_reference,
                source_section=section,
                checkpoint_core_scope=row_index <= 46,
                key=key,
                entry_type=data.get("entry_type", "article"),
                title=data.get("title", ""),
                authors=data.get("authors", []),
                year=str(data.get("year", "")),
                venue=data.get("venue", ""),
                doi=data.get("doi", ""),
                arxiv=data.get("arxiv", ""),
                best_url=data.get("best_url", ""),
                pdf_url=data.get("pdf_url", ""),
                access_status=data.get("access_status", ""),
                publisher=data.get("publisher", ""),
                volume=data.get("volume", ""),
                number=data.get("number", ""),
                pages=data.get("pages", ""),
                note=data.get("note", ""),
                local_bib_key=local.key if local else "",
                local_bib_source=local.source if local else "",
            )
            records.append(record)
    return records


def strip_bib_braces(value: str) -> str:
    return value.replace("{", "").replace("}", "").replace("\\&", "&")


def bib_escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace("{", "\\{").replace("}", "\\}")


def ris_escape(value: str) -> str:
    return re.sub(r"\s+", " ", value.replace("\n", " ")).strip()


def author_bib(authors: list[str]) -> str:
    return " and ".join(authors)


def write_bib(records: list[WorkRecord], path: Path) -> None:
    lines: list[str] = []
    for r in records:
        entry_type = "misc" if r.entry_type == "standard" else r.entry_type
        lines.append(f"@{entry_type}{{{r.key},")
        fields: list[tuple[str, str]] = [
            ("author", author_bib(r.authors)),
            ("title", r.title),
            ("year", r.year),
        ]
        if r.entry_type in {"article"} and r.venue:
            fields.append(("journal", r.venue))
        elif r.entry_type == "book" and r.publisher:
            fields.append(("publisher", r.publisher))
        elif r.entry_type in {"inproceedings"} and r.venue:
            fields.append(("booktitle", r.venue))
        elif r.venue:
            fields.append(("howpublished", r.venue))
        for name, value in [
            ("volume", r.volume),
            ("number", r.number),
            ("pages", r.pages),
            ("doi", r.doi),
            ("eprint", r.arxiv),
            ("archivePrefix", "arXiv" if r.arxiv else ""),
            ("url", r.best_url),
            ("note", r.note),
        ]:
            if value:
                fields.append((name, value))
        for name, value in fields:
            if value:
                lines.append(f"  {name} = {{{bib_escape(value)}}},")
        lines.append("}\n")
    path.write_text("\n".join(lines), encoding="utf-8")


def write_ris(records: list[WorkRecord], path: Path) -> None:
    type_map = {
        "article": "JOUR",
        "inproceedings": "CONF",
        "book": "BOOK",
        "standard": "STD",
        "misc": "GEN",
    }
    lines: list[str] = []
    for r in records:
        lines.append(f"TY  - {type_map.get(r.entry_type, 'GEN')}")
        for author in r.authors:
            lines.append(f"AU  - {ris_escape(author)}")
        lines.append(f"TI  - {ris_escape(r.title)}")
        if r.venue:
            tag = "JO" if r.entry_type == "article" else "T2"
            lines.append(f"{tag}  - {ris_escape(r.venue)}")
        if r.year:
            lines.append(f"PY  - {r.year}")
        for tag, value in [
            ("VL", r.volume),
            ("IS", r.number),
            ("SP", r.pages),
            ("DO", r.doi),
            ("UR", r.best_url or r.pdf_url),
            ("N1", r.note),
        ]:
            if value:
                lines.append(f"{tag}  - {ris_escape(value)}")
        if r.arxiv:
            lines.append(f"AN  - arXiv:{r.arxiv}")
        if r.attachment_path:
            lines.append(f"L1  - {r.attachment_path}")
        lines.append("ER  -")
        lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")


def write_json(records: list[WorkRecord], path: Path) -> None:
    payload = [r.__dict__ for r in records]
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def write_csv(records: list[WorkRecord], path: Path) -> None:
    fieldnames = list(records[0].__dict__.keys()) if records else []
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for r in records:
            row = r.__dict__.copy()
            row["authors"] = "; ".join(r.authors)
            writer.writerow(row)


def safe_filename(record: WorkRecord) -> str:
    lead = "unknown"
    if record.authors:
        lead = re.sub(r"[^A-Za-z0-9]+", "", record.authors[0].split(",", 1)[0]) or "unknown"
    stem = f"{lead}_{record.year}_{record.key}"
    stem = re.sub(r"[^A-Za-z0-9._-]+", "_", stem)
    return stem[:120] + ".pdf"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def download_pdf(record: WorkRecord, target_dir: Path, timeout: int = 15) -> None:
    if not record.pdf_url:
        record.download_status = "metadata_only"
        return

    target = target_dir / safe_filename(record)
    if target.exists() and target.stat().st_size > 1024:
        record.attachment_path = str(target)
        record.attachment_sha256 = sha256_file(target)
        record.download_status = "already_exists"
        return

    command = [
        "curl",
        "-L",
        "--fail",
        "--connect-timeout",
        "10",
        "--max-time",
        str(timeout),
        "-A",
        "Mozilla/5.0 (compatible; TWMReferenceCollector/1.0)",
        "-o",
        str(target),
        record.pdf_url,
    ]
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=timeout + 5)
    except subprocess.TimeoutExpired:
        if target.exists():
            target.unlink()
        record.download_status = "failed"
        record.download_error = f"Download exceeded {timeout + 5}s outer timeout."
        return
    if result.returncode != 0:
        if target.exists():
            target.unlink()
        record.download_status = "failed"
        record.download_error = (result.stderr or result.stdout).strip()[:500]
        return
    if target.stat().st_size <= 1024:
        target.unlink(missing_ok=True)
        record.download_status = "failed"
        record.download_error = "Downloaded file too small to be a valid PDF."
        return
    with target.open("rb") as handle:
        header = handle.read(5)
    if header != b"%PDF-":
        # Some servers return HTML with 200; keep it out of Zotero.
        target.unlink(missing_ok=True)
        record.download_status = "failed"
        record.download_error = "Downloaded response was not a PDF."
        return
    record.attachment_path = str(target)
    record.attachment_sha256 = sha256_file(target)
    record.download_status = "downloaded"


def attach_existing_pdf(record: WorkRecord, target_dir: Path) -> None:
    target = target_dir / safe_filename(record)
    if not target.exists() or target.stat().st_size <= 1024:
        return
    with target.open("rb") as handle:
        if handle.read(5) != b"%PDF-":
            return
    record.attachment_path = str(target)
    record.attachment_sha256 = sha256_file(target)
    record.download_status = "already_exists"


def write_metadata_only(records: list[WorkRecord], path: Path) -> None:
    rows = [r for r in records if not r.attachment_path]
    lines = ["# TWM metadata-only references", ""]
    for r in rows:
        lines.append(f"- `{r.key}` ({r.year}) {r.title}")
        lines.append(f"  - status: {r.access_status or r.download_status}")
        if r.best_url:
            lines.append(f"  - url: {r.best_url}")
        if r.download_error:
            lines.append(f"  - download_error: {r.download_error}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_summary(records: list[WorkRecord], path: Path) -> None:
    total = len(records)
    source_rows = len({r.source_index for r in records})
    checkpoint_records = len([r for r in records if r.checkpoint_core_scope])
    downloaded = len([r for r in records if r.attachment_path])
    local = len([r for r in records if r.local_bib_key])
    metadata_only = len([r for r in records if not r.attachment_path])
    failed = [r for r in records if r.download_status == "failed"]
    lines = [
        "# TWM authoritative reference import summary",
        "",
        f"- Source Markdown: `{SOURCE_MD.relative_to(REPO_ROOT)}`",
        f"- Source table rows: {source_rows}",
        f"- Work records: {total}",
        f"- Checkpoint core-scope records: {checkpoint_records}",
        f"- Local BibTeX matches reused: {local}",
        f"- PDF attachments present: {downloaded}",
        f"- Metadata-only records: {metadata_only}",
        f"- Failed PDF downloads: {len(failed)}",
        f"- Zotero attachment directory: `{ZOTERO_COLLECTION_DIR}`",
        "",
        "## Outputs",
        "",
        "- `twm_authoritative_references.json`",
        "- `twm_authoritative_references.csv`",
        "- `twm_authoritative_references.bib`",
        "- `twm_authoritative_references.ris`",
        "- `metadata_only.md`",
        "",
        "The same sidecar files are copied beside the PDFs in the Zotero attachment directory.",
        "",
    ]
    if failed:
        lines.extend(["## Failed Downloads", ""])
        for r in failed:
            lines.append(f"- `{r.key}`: {r.download_error}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--skip-downloads", action="store_true", help="Generate metadata files but do not download PDFs.")
    parser.add_argument("--output-dir", type=Path, default=OUTPUT_DIR)
    parser.add_argument("--zotero-dir", type=Path, default=ZOTERO_COLLECTION_DIR)
    args = parser.parse_args()

    rows = extract_source_rows(SOURCE_MD)
    local_entries = load_local_bib_entries()
    records = build_records(rows, local_entries)

    args.output_dir.mkdir(parents=True, exist_ok=True)
    args.zotero_dir.mkdir(parents=True, exist_ok=True)

    if not args.skip_downloads:
        for idx, record in enumerate(records, start=1):
            print(f"[{idx:02d}/{len(records)}] {record.key}: {record.title}", flush=True)
            download_pdf(record, args.zotero_dir)
            print(f"  -> {record.download_status}", flush=True)
            time.sleep(0.2)
    else:
        for record in records:
            attach_existing_pdf(record, args.zotero_dir)

    output_files = {
        "twm_authoritative_references.json": args.output_dir / "twm_authoritative_references.json",
        "twm_authoritative_references.csv": args.output_dir / "twm_authoritative_references.csv",
        "twm_authoritative_references.bib": args.output_dir / "twm_authoritative_references.bib",
        "twm_authoritative_references.ris": args.output_dir / "twm_authoritative_references.ris",
        "metadata_only.md": args.output_dir / "metadata_only.md",
        "SUMMARY.md": args.output_dir / "SUMMARY.md",
    }
    write_json(records, output_files["twm_authoritative_references.json"])
    write_csv(records, output_files["twm_authoritative_references.csv"])
    write_bib(records, output_files["twm_authoritative_references.bib"])
    write_ris(records, output_files["twm_authoritative_references.ris"])
    write_metadata_only(records, output_files["metadata_only.md"])
    write_summary(records, output_files["SUMMARY.md"])

    for name, source_path in output_files.items():
        shutil.copy2(source_path, args.zotero_dir / name)

    print(f"Wrote outputs to {args.output_dir}")
    print(f"Zotero attachments in {args.zotero_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
