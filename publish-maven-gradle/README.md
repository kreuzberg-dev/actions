# publish-maven-gradle

Publish a Gradle-built JVM project (Kotlin, Java/Gradle, Android libraries)
to Maven Central with GPG signing.

This is the Gradle-flavoured sibling of `publish-maven`, which targets
Maven (`mvn deploy`) projects.

## Supported plugins

The action invokes a single Gradle task. The most common publish setups are:

- **[vanniktech.maven.publish](https://vanniktech.github.io/gradle-maven-publish-plugin/)**
  (recommended): one-line `publishAndReleaseToMavenCentral` does the full
  staging-and-release dance against the new Sonatype Central Portal.
- **vanilla `maven-publish` + `signing`**: invoke `publish`, then close +
  release the staging repository manually on https://central.sonatype.com.

## Authentication

| Env var | Purpose |
|---|---|
| `MAVEN_USERNAME` | Sonatype Central Portal user token (top half) |
| `MAVEN_PASSWORD` | Sonatype Central Portal user token (bottom half) |
| `MAVEN_GPG_PRIVATE_KEY` | ASCII-armored GPG private key for signing |
| `MAVEN_GPG_PASSPHRASE` | passphrase for the GPG key |

Auth is read from `env`, **not** from `inputs`, so callers should set them
at the job/step level:

```yaml
env:
  MAVEN_USERNAME: ${{ secrets.CENTRAL_USERNAME }}
  MAVEN_PASSWORD: ${{ secrets.CENTRAL_PASSWORD }}
  MAVEN_GPG_PRIVATE_KEY: ${{ secrets.GPG_PRIVATE_KEY }}
  MAVEN_GPG_PASSPHRASE: ${{ secrets.GPG_PASSPHRASE }}
```

The action exposes these to the Gradle JVM via the `ORG_GRADLE_PROJECT_*`
convention, which both the vanniktech plugin and the vanilla `signing`
plugin read automatically (`mavenCentralUsername`, `mavenCentralPassword`,
`signingInMemoryKey`, `signingInMemoryKeyPassword`).

## Usage

```yaml
jobs:
  publish-kotlin:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: kreuzberg-dev/actions/publish-maven-gradle@v1
        env:
          MAVEN_USERNAME: ${{ secrets.CENTRAL_USERNAME }}
          MAVEN_PASSWORD: ${{ secrets.CENTRAL_PASSWORD }}
          MAVEN_GPG_PRIVATE_KEY: ${{ secrets.GPG_PRIVATE_KEY }}
          MAVEN_GPG_PASSPHRASE: ${{ secrets.GPG_PASSPHRASE }}
        with:
          working-directory: packages/kotlin
          gradle-task: publishAndReleaseToMavenCentral
```

### Dry run

```yaml
- uses: kreuzberg-dev/actions/publish-maven-gradle@v1
  with:
    working-directory: packages/kotlin
    dry-run: 'true'
```

## Inputs

| Name | Required | Default | Description |
|---|---|---|---|
| `working-directory` | no | `.` | Project root (containing `build.gradle.kts` or `build.gradle`). |
| `gradle-task` | no | `publishAndReleaseToMavenCentral` | Gradle task to invoke. |
| `extra-args` | no | `""` | Additional Gradle args. |
| `no-daemon` | no | `true` | Pass `--no-daemon` to Gradle. |
| `setup-gradle` | no | `true` | Run `gradle/actions/setup-gradle@v6`. |
| `setup-java` | no | `true` | Run `actions/setup-java@v5`. |
| `java-version` | no | `21` | JDK version when `setup-java=true`. |
| `dry-run` | no | `false` | Print the command without executing. |

## Idempotency

If Gradle reports the version is already released or published (matched
case-insensitively against the output), the action exits 0. This makes it
safe to re-run a release workflow on a partially-published tag.
