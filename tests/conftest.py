"""Gemeinsame Testumgebung – wird vor allen Testdateien geladen."""
import os
import tempfile

os.environ["ITD_DATA_DIR"] = tempfile.mkdtemp()
os.environ["ITD_ADMIN_PASSWORD"] = "admin-passwort"
os.environ["ITD_PUBLIC_URL"] = "https://doku.example.de"
os.environ["ITD_SCHEDULER"] = "0"
os.environ["ITD_UPDATE_CHECK"] = "0"
os.environ["ITD_SELF_RESTART"] = "0"
os.environ["ITD_KDF_ITERATIONS"] = "1000"  # Tests: schnell statt sicher
os.environ["ITD_HTTP_ACCESS"] = "1"  # TestClient spricht http – die Sperre wird in test_security_review.py eigens geprüft
