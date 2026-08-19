from pathlib import Path


K8S_ROOT = Path(__file__).resolve().parents[1]


def test_bank_namespaces_are_provisioned_before_secrets_and_survive_rotation_toggle():
    source = (K8S_ROOT / "15-bank-jwt-secret.tf").read_text(encoding="utf-8")

    assert 'resource "kubectl_manifest" "bank_namespace"' not in source
    assert 'resource "kubernetes_namespace_v1" "bank"' in source
    assert "from = kubectl_manifest.bank_namespace" in source
    removed_block = source.split("removed {", 1)[1].split(
        'resource "kubernetes_namespace_v1"', 1
    )[0]
    assert "destroy = false" in removed_block

    namespace_block = source.split('resource "kubernetes_namespace_v1" "bank"', 1)[1]
    namespace_block = namespace_block.split('resource "kubernetes_secret_v1"', 1)[0]
    assert 'for_each = toset(["frontend", "backend"])' in namespace_block
    assert "enable_bank_jwt_rotation" not in namespace_block


def test_rotation_only_gates_secret_inputs_and_secret_resource():
    source = (K8S_ROOT / "15-bank-jwt-secret.tf").read_text(encoding="utf-8")
    conditional = 'var.enable_bank_jwt_rotation ? toset(["frontend", "backend"]) : toset([])'

    assert 'count = var.enable_bank_jwt_rotation ? 1 : 0' in source
    assert source.count(conditional) == 1
    assert 'resource "kubernetes_secret_v1" "bank_jwt"' in source
    assert (
        'namespace = kubernetes_namespace_v1.bank[each.key].metadata[0].name'
        in source
    )


def test_rotation_defaults_to_enabled():
    variables = (K8S_ROOT / "variables.tf").read_text(encoding="utf-8")
    block = variables.split('variable "enable_bank_jwt_rotation"', 1)[1].split("}", 1)[0]

    assert "default     = true" in block
