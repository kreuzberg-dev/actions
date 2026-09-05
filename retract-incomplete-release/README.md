# retract-incomplete-release

Return a GitHub Release to draft after a publish run failed to reach every enabled
target — but only while no downstream channel has already been pointed at it.

A publish run creates the release as a draft, promotes it out of draft early so
`cargo-binstall` and the bottle builders have resolvable assets, then publishes the
registry targets. When a target fails, the run wants the release back in the draft
state it would never have left.

That is safe right up until a channel has been pointed at the release. A Homebrew
formula pins `root_url .../releases/download/<tag>` and a Scoop manifest pins the
same asset URLs; once either is pushed to its public tap or bucket, the draft state
stops being private bookkeeping and becomes a 404 for every `brew upgrade` and
`scoop update` in the world — see xberg-io/crawlberg#41, where a re-drafted `v1.5.0`
left the tap advertising assets nobody could download.

So retraction is conditional. No consumer published → retract. A consumer published
→ report the incomplete release loudly and leave it published, to be rolled forward
by the next release.

The action never fails the step: the caller has already failed the job on the
release verdict, and a retraction problem is reported rather than stacked on top.

## Inputs

| Name | Required | Default | Description |
|---|---|---|---|
| `tag` | yes | — | Git tag of the release to retract. |
| `consumer-results` | no | `""` | Results of the jobs publishing a channel that resolves `.../releases/download/<tag>/...`. Comma- or newline-separated; entries may be bare (`success`) or named (`homebrew=success`). Any `success` blocks retraction. Empty means no such consumers, so retraction always proceeds. |
| `dry-run` | no | `false` | Print the intended action without modifying the release. |
| `token` | no | `${{ github.token }}` | GitHub token. |

## Outputs

| Name | Description |
|---|---|
| `retracted` | `true`, `blocked`, `dry-run`, or `error`. |
| `blocking-consumers` | Comma-separated names of the consumers that blocked retraction. |

## Usage

```yaml
- name: Hold release as draft
  if: failure()
  uses: xberg-io/actions/retract-incomplete-release@v1
  with:
    tag: ${{ needs.prepare.outputs.tag }}
    consumer-results: |
      homebrew=${{ needs.publish-homebrew-formula.result }}
      homebrew-bottles=${{ needs.publish-homebrew-bottles.result }}
      scoop=${{ needs.publish-scoop-manifest.result }}
    token: ${{ steps.app-token.outputs.token }}
```

Name the jobs that push to the **tap and bucket**, not the jobs that build bottles
into the release — the release's own assets are what the draft state hides, so
uploading them is not what makes retraction unsafe. Pushing a formula that points
at them is.

## Notes

- Requires `permissions: contents: write` on the calling job (or a token with it).
- Idempotent: re-drafting an already-drafted release is a no-op that still reports
  `retracted=true`.
