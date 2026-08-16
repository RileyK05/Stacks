def test_packages_importable() -> None:
    import src.backend.common  # noqa: F401
    import src.backend.evals  # noqa: F401
    import src.backend.ingest  # noqa: F401
    import src.backend.memory  # noqa: F401
    import src.backend.retrieval  # noqa: F401
    import src.backend.student_model  # noqa: F401
    import src.backend.tutor  # noqa: F401
