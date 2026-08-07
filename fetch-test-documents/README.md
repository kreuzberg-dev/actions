# fetch-test-documents

Materialise binary fixtures from the public `xberg-test-documents` GCS bucket into a checked-out
`test_documents` submodule, replacing `git lfs pull`. Objects are content-addressed
(`objects/<sha256>`) and served publicly and anonymously at
`https://storage.googleapis.com/xberg-test-documents/objects/<sha256>` — no credentials, no gcloud
SDK, works on fork PRs and self-hosted runners.

Most CI jobs need only a handful of fixture files, not the full corpus, so `include` selects a
subset via glob patterns matched against manifest paths in `<path>/corpus.lock.json`. Matching
entries are deduped by sha256 (some paths share an identical object), each unique object is
downloaded in parallel and its checksum verified, then copied to every path that references it. A
checksum mismatch — on download or when reusing a cached object — fails the step.

## Inputs

| Name | Required | Default | Description |
|---|---|---|---|
| `path` | no | `test_documents` | Directory where the `test_documents` submodule is checked out. |
| `include` | no | `**` | Newline-separated glob patterns matched against manifest paths (e.g. `pdf/**`). |
| `bucket` | no | `xberg-test-documents` | GCS bucket serving objects at `https://storage.googleapis.com/<bucket>/objects/<sha256>`. |
| `cache` | no | `true` | Cache downloaded objects via `actions/cache`, keyed by the manifest content and normalised include patterns. |
| `concurrency` | no | `8` | Number of objects to download in parallel. |

## Outputs

| Name | Description |
|---|---|
| `cache-hit` | Whether the object cache was restored on an exact key match. |
| `objects-fetched` | Number of unique objects downloaded from the bucket this run (`0` on a full cache hit). |
| `bytes-fetched` | Total bytes downloaded from the bucket this run. |

## Example

```yaml
- uses: actions/checkout@v7
  with:
    submodules: true

- uses: xberg-io/actions/fetch-test-documents@v1
  with:
    include: |
      pdf/**
      images/**
```

Fetch everything (default):

```yaml
- uses: xberg-io/actions/fetch-test-documents@v1
```

## Notes

- Patterns are bash `[[ path == pattern ]]` matches, not gitignore-style globs, so `*` crosses `/`:
  `pdf/*` and `pdf/**` both select everything under `pdf/`, at any depth. There is no way to match a
  single path segment.
- Fails early with a clear error if `<path>/corpus.lock.json` is missing — check out the
  `test_documents` submodule first (`actions/checkout` with `submodules: true`, or a dedicated
  checkout step).
- Safe to run twice in the same job: already-cached objects are re-verified against their expected
  sha256 rather than re-downloaded, and a corrupted cache entry is detected and re-fetched instead
  of silently reused.
- The read path needs zero credentials by design; do not add authentication to this action.
