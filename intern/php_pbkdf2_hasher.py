import base64
import hashlib

from django.contrib.auth.hashers import BasePasswordHasher
from django.utils.crypto import constant_time_compare


class PHP_PBKDF2Hasher(BasePasswordHasher):
    algorithm = "php_sha256"

    def verify(self, password, encoded):
        """
        encoded = sha256:100000:salt_base64:hash_base64
        """
        try:
            algo, iterations, salt_b64, hash_b64 = encoded.split("$")
        except ValueError:
            return False

        iterations = int(iterations)
        salt = salt_b64.encode("utf-8")

        derived = hashlib.pbkdf2_hmac(
            "sha256",
            password.encode("utf-8"),
            salt,
            iterations,
            dklen=len(base64.b64decode(hash_b64)),
        )

        return constant_time_compare(
            base64.b64encode(derived).decode("ascii"),
            hash_b64,
        )

    def encode(self, password, salt):
        raise NotImplementedError("Dieser Hasher ist nur für Legacy-Validierung")

    def safe_summary(self, encoded):
        algo, iterations, salt, hash_ = encoded.split(":")
        return {
            "algorithm": algo,
            "iterations": iterations,
            "salt": salt,
            "hash": hash_[:6] + "...",
        }
