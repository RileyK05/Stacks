"""Course-knowledge subsystem: concept/dependency extraction and the
table of contents for uploaded course material.

Despite the package name (a legacy misnomer), this is NOT the memory
subsystem of decision 007. It builds the shared, per-course knowledge
layer — what the course SAYS (concepts, formulas, theorems, with
evidence) and the TOC index used to FIND content. Per-user course memory
(the focus node) lives in common/course_memory.py; user memory (the
behavioral root) is Milestone 2 work. See docs/decisions/007_memory_model.md.
"""