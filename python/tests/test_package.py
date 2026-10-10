"""Test de fumée : le paquet logicai doit être importable depuis les tests."""

import logicai


def test_package_is_importable() -> None:
    # Règle vérifiée : infrastructure de la phase 0 (pythonpath = ["src"] dans pytest).
    assert logicai.__doc__ is not None
