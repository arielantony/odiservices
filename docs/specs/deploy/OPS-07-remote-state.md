# Spec — OPS-07 Remote OpenTofu state in S3

| | |
|---|---|
| **Backlog** | Packaging and deployment › Infrastructure › OPS-07 |
| **Depends on** | OPS-03 |
| **Spec status** | Approved, 2026-11-01 (approved by the owner when #45 merged). Owner decisions of 2026-11-01 are applied: S3 native locking (`use_lockfile`), SSE-S3, a separate bootstrap configuration, bucket `odiservices-tofu-state-<account-id>` in `us-east-2`, versioning, public access blocked, TLS only, 90 days of old versions |
| **Date** | 2026-11-01 |

## 1. Goal

Move the OpenTofu state of `infra/tofu/` out of a git worktree and into a
private, versioned, locked S3 bucket. Today the only record of the Lightsail
instance, its static IP and its firewall is `terraform.tfstate` inside
`.worktrees/feature/ops-03-lightsail/`, a directory that scripts and people
delete. After this item, any checkout of the repository plus the operator's AWS
profile can run `tofu plan`, and two runs cannot write the state at once.

## 2. Scope

**In scope**

- `infra/tofu-bootstrap/`: a small configuration, with **local** state, that
  creates only the state bucket (section 3.1).
- `infra/tofu/backend.tf` and `backend.hcl.example`: the `s3` backend as a
  partial configuration (section 3.2).
- Migrating the existing state (section 3.3).
- `make infra-check` covers both directories. `test_infra_files.py` gains the
  tests of section 5.
- `docs/deploy/lightsail.md`: where the state lives, how to recover a version,
  how to run `tofu` from a fresh checkout.

**Out of scope**

- Moving the bootstrap state itself into S3: it would need the bucket it
  creates (question 1).
- A DynamoDB lock table: `use_lockfile` replaces it (decision 1).
- KMS keys: SSE-S3 is enough, because the state holds no secret (OPS-03,
  check 15).
- Cross-account access, CI roles and state for other stacks (ECR in OPS-06 may
  reuse this bucket under another key later).

## 3. Design

### 3.1 The bootstrap (`infra/tofu-bootstrap/`)

| File | Content |
|---|---|
| `versions.tf` | `required_version >= 1.10.0`; the `aws` provider pinned to the same exact version as `infra/tofu/`; `.terraform.lock.hcl` committed |
| `variables.tf` | `region` (default `us-east-2`), `bucket_name` (no default) |
| `main.tf` | The bucket and its settings (below) |
| `outputs.tf` | `bucket_name`, `region`. No secret |
| `terraform.tfvars.example` | `bucket_name = "odiservices-tofu-state-<account-id>"` |

The bucket's settings, each a separate resource in the AWS provider:

| Setting | Value |
|---|---|
| Versioning | Enabled |
| Encryption | SSE-S3 (`AES256`), bucket key on |
| Public access block | All four settings `true` |
| Ownership | `BucketOwnerEnforced` (no ACLs) |
| Policy | Deny every `s3:*` on the bucket and its objects when `aws:SecureTransport` is `false` |
| Lifecycle | Expire noncurrent versions after 90 days; abort incomplete multipart uploads after 7 days. Current versions never expire |
| Protection | `lifecycle { prevent_destroy = true }` |

The bootstrap state (`infra/tofu-bootstrap/terraform.tfstate`) stays local and
git-ignored, like `terraform.tfvars`. It describes one bucket and can be
rebuilt with `tofu import`; the runbook says so and tells the owner to copy it
to `~/odiservices-backups/`.

### 3.2 The backend (`infra/tofu/`)

`backend.tf` holds `terraform { backend "s3" {} }` and nothing else, because a
backend block cannot read variables. The values come from `backend.hcl`
(git-ignored, with a committed `backend.hcl.example`):

```hcl
bucket       = "odiservices-tofu-state-<account-id>"
key          = "odiservices/lightsail/terraform.tfstate"
region       = "us-east-2"
encrypt      = true
use_lockfile = true
```

`tofu init -backend-config=backend.hcl` selects it. Credentials come from the
AWS profile, as for the provider. `make infra-check` keeps running
`tofu init -backend=false`, so it needs no credentials.

### 3.3 Migrating the state

1. Copy the live state to `~/odiservices-backups/` (already done on
   2026-11-01; repeat it right before, and compare with `cmp`).
2. In the directory that holds the state, run
   `tofu init -backend-config=backend.hcl -migrate-state`, and answer yes.
3. `tofu state list` shows the same 5 resources, and `tofu plan` shows
   "No changes".
4. Remove the local `terraform.tfstate` and `terraform.tfstate.backup`
   (the backup copy stays). From then on `.worktrees/feature/ops-03-lightsail`
   holds no state, and its saved plans can be deleted.

### 3.4 The permission the owner provides

The `odiservices-tofu` user needs, on the one bucket and nothing else:

```json
{
  "Version": "2012-10-17",
  "Statement": [{
    "Effect": "Allow",
    "Action": "s3:*",
    "Resource": [
      "arn:aws:s3:::odiservices-tofu-state-<account-id>",
      "arn:aws:s3:::odiservices-tofu-state-<account-id>/*"
    ]
  }]
}
```

`s3:CreateBucket` is checked against the bucket ARN, so this one statement
covers the creation too. It gives no `s3:ListAllMyBuckets` and no access to any
other bucket. The agent never creates or edits IAM.

### 3.5 Steps

| Step | Branch | Content |
|---|---|---|
| 1 | `feat/ops-07-step-1-bucket` | The owner attaches the bucket policy (3.4), done 2026-11-01; `infra/tofu-bootstrap/`, `.gitignore` entries, `make infra-check` for both, the step 1 tests, the bucket created and the smoke tests (checks 4 to 9) |
| 2 | `feat/ops-07-step-2-migrate` | `backend.tf`, `backend.hcl.example`, the migration, the runbook, the remaining tests (checks 10 to 15), OPS-07 set to Done |

Both stay under 500 changed lines. The feature branch is
`feature/ops-07-remote-state`, and a final PR takes it to `main`.

## 4. Verification

The owner runs the rows marked *owner*. Each live check has a timeout of 120
seconds, except where noted.

| # | Step | Check | Expected |
|---|---|---|---|
| 1 | 1 | `make infra-check` | Passes for `infra/tofu` and `infra/tofu-bootstrap`, with no AWS credentials |
| 2 | 1 | `test_infra_files.py` | Passes (section 5) |
| 3 | 1 | `git check-ignore infra/tofu-bootstrap/terraform.tfstate infra/tofu-bootstrap/terraform.tfvars infra/tofu/backend.hcl` | All three are ignored |
| 4 | 1 | *Owner:* `tofu plan` in `infra/tofu-bootstrap` (agent asks "go") | Plans 1 bucket plus its settings, 0 to change, 0 to destroy |
| 5 | 1 | *Owner:* `tofu apply` of that saved plan (agent asks "apply") | Succeeds. This is also the proof that the profile may create the bucket (section 8) |
| 6 | 1 | `aws s3api get-bucket-versioning`, `get-bucket-encryption`, `get-public-access-block`, `get-bucket-policy`, `get-bucket-lifecycle-configuration` | `Enabled`; `AES256`; four `true`; the policy denies when `SecureTransport` is `false`; the two lifecycle rules |
| 7 | 1 | `curl -s -o /dev/null -w '%{http_code}' https://<bucket>.s3.us-east-2.amazonaws.com/` with no credentials | `403` |
| 8 | 1 | A throwaway configuration in the scratchpad (one `terraform_data` with a `local-exec` `sleep 40`) with the `s3` backend on the key `smoke/terraform.tfstate`. Start `tofu apply` in the background and, 10 seconds later, run `tofu plan -lock-timeout=0s` | The second command fails with `Error acquiring the state lock`. After the apply ends, a plan runs normally |
| 9 | 1 | `aws s3api list-object-versions --prefix smoke/`, then `aws s3api delete-object` for each version | Two or more versions were listed, and the prefix is empty afterwards |
| 10 | 2 | `cmp` the live state against the backup in `~/odiservices-backups/`, then `tofu init -backend-config=backend.hcl -migrate-state` (agent asks "go") | Identical before; the migration reports success |
| 11 | 2 | `aws s3api head-object` on the state key, then `tofu state list` | The object exists; 5 resources |
| 12 | 2 | *Owner:* `tofu plan` in `infra/tofu` (agent asks "go") | "No changes" |
| 13 | 2 | In a fresh worktree, with only `terraform.tfvars` and `backend.hcl` copied in, `tofu init -backend-config=backend.hcl` and `tofu plan` | "No changes". Nothing is read from a local state |
| 14 | 2 | Recovery: `aws s3api list-object-versions` on the state key, then `aws s3api get-object --version-id <previous>` into the scratchpad, and read `serial` from the current and the older copy with `jq .serial` | At least two versions; the older `serial` is lower |
| 15 | 2 | `ls infra/tofu/terraform.tfstate*` in the old worktree | No such files. The backup directory still has the state |

## 5. Tests

`app/api/tests/test_infra_files.py` reads the files and asserts, with no AWS
call and no fixture beyond the repository files:

| Test | Asserts |
|---|---|
| `test_bootstrap_bucket_is_hardened` | The bootstrap declares versioning `Enabled`, `AES256`, all four public-access settings `true`, `BucketOwnerEnforced`, a `SecureTransport` deny, a lifecycle rule and `prevent_destroy = true` |
| `test_bootstrap_provider_matches_main` | The `aws` provider version in both directories is the same exact pin, and both lock files are committed |
| `test_bootstrap_has_no_bucket_name_default` | `bucket_name` has no default, so the account id never reaches the repository |
| `test_backend_is_partial_and_locked` | `backend.tf` declares `backend "s3"` with no bucket or key, and `backend.hcl.example` has `encrypt = true` and `use_lockfile = true` |
| `test_state_and_backend_files_are_ignored` | `.gitignore` covers `*.tfstate`, `*.tfvars` and `backend.hcl` but not `backend.hcl.example` |

## 6. Open questions

1. **The bootstrap state.** Recommended: keep it local, git-ignored, with a
   copy in `~/odiservices-backups/`. Putting it in the same bucket is circular.
2. **One bucket or one per stack.** Recommended: one bucket, one key per stack
   (`odiservices/lightsail/…`, later `odiservices/ecr/…`).
3. **`terraform.tfvars` and `backend.hcl` are local.** Recommended: keep a copy
   of both in `~/odiservices-backups/`. Moving them to a secrets store is
   OPS-05's concern.

## 7. Prerequisites

| Prerequisite | Provider | Preflight | Expected |
|---|---|---|---|
| OpenTofu with `use_lockfile` (1.10 or newer) | agent | `tofu version` | `v1.13.2`. **Green** (2026-11-01) |
| A scoped, non-root identity | owner | `AWS_PROFILE=odiservices-tofu aws sts get-caller-identity` | `…:user/odiservices-tofu`. **Green** |
| The bucket name is free | agent | `aws s3api head-bucket --bucket <name>` | `404`. **Green** for `odiservices-tofu-state-<account-id>` |
| The live state is intact and backed up | agent | `cmp` the live state against `~/odiservices-backups/tofu-state-2026-11-01/`, and `tofu state list` | Identical; 5 resources. **Green** |
| Inventory | agent | The AWS account has no bucket for this purpose | Assumed none: `ListAllMyBuckets` is denied to the profile, so the agent cannot list. The 404 above covers the name only |
| Cost | | The bucket holds a few kilobytes | Under US$0.05 a month. A failed attempt costs nothing. The owner removes a leftover bucket by emptying its versions and removing `prevent_destroy` |

No package is installed. `tofu` and `aws` are already on the machine.

## 8. Assumptions to verify

1. **`use_lockfile` works in OpenTofu 1.13.2 with the `s3` backend.** *Assumed*
   from the release notes (introduced in 1.10). Check 8 is its smoke test and
   runs in step 1, before the state moves.
2. **`head-bucket` cannot prove permission.** *Verified* today: S3 answers 404
   for a bucket that does not exist, whatever the caller may do, and the IAM
   read calls are denied to the profile. Consequence: the apply of check 5
   is the permission test, and a 403 there means the policy is missing or the
   name belongs to someone else.
3. **A policy on the bucket ARN is enough for `s3:CreateBucket`.** *Assumed*
   from the S3 documentation. If check 5 fails with `AccessDenied`, the
   owner widens the resource to `arn:aws:s3:::odiservices-*` and the spec is
   updated.
4. **`tofu init -migrate-state` copies the state with its lineage and serial.**
   *Assumed.* Check 10 compares the object with the local copy; the backup
   remains if it does not.
5. **The AWS provider 6.71.0 has the S3 resources named in section 3.1.**
   *Assumed.* `make infra-check` (`tofu validate`) proves it in step 1.

## 9. Approvals

| Action | Who | Standing answer |
|---|---|---|
| Attach the bucket policy in IAM (a step of this item, section 3.5) | Owner | Done on 2026-11-01. The agent never creates or edits IAM |
| `tofu plan` (bootstrap, main) | Owner says "go" | One saved plan each |
| `tofu apply` of the bootstrap plan | Owner says "apply" | One saved plan |
| `tofu init -migrate-state` | Owner says "go" | Once, after the backup is compared |
| Throwaway configuration under `smoke/` in the bucket, deleted after | Agent | Approved by this spec |
| Remove the local state files after the migration | Agent | Approved by this spec, only after check 11 passes |
| Destroy the bucket | Owner | Never in this item (`prevent_destroy`) |
