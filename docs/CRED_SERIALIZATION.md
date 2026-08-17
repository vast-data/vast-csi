# Helm: EV credential serialization

Two new chart values control how CSI inline ephemeral volume (EV) credentials are stored in node-local `.vast-csi-meta`, and whether old metadata can still be unpublished.

Applies to `vastcsi`, `vastblock`, and the operator `vastcsidriver` chart.

| Value | Default | Purpose |
|---|---|---|
| `credSerializationSecret` | `""` | Kubernetes secret used to encrypt new EV metadata |
| `fallbackToDeser` | `false` (disabled) | Allow unpublish of EV volumes published with the old serializer |

## `credSerializationSecret`

Name of a Secret in the driver namespace. The node plugin mounts it at `/opt/cred-serde`. The Secret **must** contain a key named `key`.

```bash
kubectl create secret generic vast-cred-serde \
  --from-literal=key="$(openssl rand -base64 32)"
```

```yaml
credSerializationSecret: vast-cred-serde
```

| Setting | New publishes |
|---|---|
| unset / `""` | Plaintext JSON (`format: plain`). |
| set | AES-GCM (`format: encrypted`). Key is derived as `HKDF(secret, volume_id)`. |

Do not rotate or delete this secret while an encrypted EV is still mounted. Unpublish needs the same `key` that publish used.

## `fallbackToDeser`

The previous serializer wrote AES-CFB + pickle, keyed only by `SHA-256(volume_id)`, with `.vast-csi-meta` on local disk (no tmpfs). New publishes never write that format.

Default is **`false`** (disabled). Helm still fails if the value is unset/`null` rather than a boolean.

| Setting | Unpublish of **already mounted** EVs |
|---|---|
| `false` (default) | Rejects leftover pickle (`legacy serialized metadata rejected`) |
| `true` | Reads old pickle metadata and meta on local disk with no tmpfs |
| unset / `null` | Helm fails: `fallbackToDeser must be set explicitly to true or false` |

New publishes always use tmpfs + JSON (plain or encrypted). This flag does not change new publishes.

Already-mounted old EVs cannot be converted in place.

## Migration

If the cluster has no CSI inline EV volumes from before this upgrade, leave `fallbackToDeser: false` (the chart default).

If old EV volumes are still mounted:

1. Upgrade with **`fallbackToDeser: true`**. Optionally set `credSerializationSecret` in the same upgrade so **new** publishes are encrypted. Old mounted EVs unpublish via fallback.

```yaml
fallbackToDeser: true
credSerializationSecret: vast-cred-serde   # optional
```

2. Restart or delete every pod that still has a CSI inline EV from before the upgrade, so those volumes unpublish with fallback and republish with the new format.

3. When none of those old EVs remain mounted, set `fallbackToDeser: false` and `helm upgrade`.

If unpublish fails with `legacy serialized metadata rejected (fallbackToDeser=false)`, set `fallbackToDeser: true`, unpublish that volume, then set `false` again.
