#!/usr/bin/env bash
set -euo pipefail

version="${1:-latest}"
install_dir="${2:-}"

task_bin_dir="${install_dir:-${RUNNER_TEMP:-${HOME}/.local}/task-bin}"
mkdir -p "$task_bin_dir"

resolve_latest_version() {
	local api_url="https://api.github.com/repos/go-task/task/releases/latest"
	local auth_args=()
	if [[ -n "${GITHUB_TOKEN:-}" ]]; then
		auth_args=(-H "Authorization: Bearer ${GITHUB_TOKEN}")
	fi
	curl --proto '=https' \
		--tlsv1.2 \
		--fail \
		--silent \
		--show-error \
		--location \
		--connect-timeout 10 \
		--max-time 30 \
		-H "X-GitHub-Api-Version: 2022-11-28" \
		-H "Accept: application/vnd.github+json" \
		"${auth_args[@]}" \
		"$api_url" |
		grep -oE '"tag_name":[[:space:]]*"[^"]+"' |
		head -1 |
		sed -E 's/.*"tag_name":[[:space:]]*"([^"]+)".*/\1/'
}

install_task() {
	local max_attempts=6
	local attempt=1
	local wait_time=5

	local resolved_version="$version"
	if [[ "$resolved_version" == "latest" || -z "$resolved_version" ]]; then
		local latest
		if latest=$(resolve_latest_version) && [[ -n "$latest" ]]; then
			echo "Resolved 'latest' to ${latest}"
			resolved_version="$latest"
		else
			echo "Warning: failed to pre-resolve 'latest' via GitHub API; falling back to installer default" >&2
		fi
	elif [[ "$resolved_version" != v* ]]; then
		# taskfile.dev's install.sh and the release URLs both take the git tag, which is
		# v-prefixed; a bare "3.51.1" fails every attempt with "unable to find '3.51.1'".
		# `latest` already resolves to a tag, so only an explicitly pinned version needs this.
		resolved_version="v${resolved_version}"
	fi

	while [[ $attempt -le $max_attempts ]]; do
		echo "Installing Task ${resolved_version} (attempt ${attempt}/${max_attempts})..."

		local installer
		installer="${RUNNER_TEMP:-$(mktemp -d)}/task-install.sh"
		if curl --proto '=https' \
			--tlsv1.2 \
			--fail \
			--silent \
			--show-error \
			--location \
			--connect-timeout 10 \
			--max-time 60 \
			--retry 2 \
			--retry-delay 3 \
			https://taskfile.dev/install.sh \
			--output "$installer"; then

			local install_args=(-b "$task_bin_dir")
			if [[ -n "$resolved_version" && "$resolved_version" != "latest" ]]; then
				install_args+=("$resolved_version")
			fi

			if sh "$installer" "${install_args[@]}"; then

				if [[ -x "$task_bin_dir/task" ]]; then
					echo "Task installation successful"
					return 0
				else
					echo "Error: Task binary not found at $task_bin_dir/task"
					rm -f "$task_bin_dir/task"
				fi
			fi
		else
			echo "Download/installation failed; trying GitHub release fallback..."
			if install_from_github_release "$resolved_version"; then
				return 0
			fi
		fi

		attempt=$((attempt + 1))
		if [[ $attempt -le $max_attempts ]]; then
			echo "Retrying in ${wait_time}s..."
			sleep "$wait_time"
			wait_time=$((wait_time * 2))
		fi
	done

	echo "Error: Failed to install Task after ${max_attempts} attempts" >&2
	return 1
}

install_from_github_release() {
	local version="${1:-latest}"
	echo "Attempting direct download from GitHub releases..."

	local os
	local arch
	case "$(uname -s)" in
	Linux)
		os="linux"
		;;
	Darwin)
		os="darwin"
		;;
	*)
		echo "Unsupported OS" >&2
		return 1
		;;
	esac

	case "$(uname -m)" in
	x86_64)
		arch="amd64"
		;;
	aarch64 | arm64)
		arch="arm64"
		;;
	*)
		echo "Unsupported architecture" >&2
		return 1
		;;
	esac

	local resolved_version="$version"
	if [[ "$resolved_version" == "latest" ]]; then
		if resolved_version=$(resolve_latest_version) && [[ -n "$resolved_version" ]]; then
			echo "Resolved 'latest' to ${resolved_version}"
		else
			echo "Failed to resolve 'latest' version" >&2
			return 1
		fi
	fi

	local download_url="https://github.com/go-task/task/releases/download/${resolved_version}/task_${os}_${arch}.tar.gz"
	local auth_args=()
	if [[ -n "${GITHUB_TOKEN:-}" ]]; then
		auth_args=(-H "Authorization: Bearer ${GITHUB_TOKEN}")
	fi

	local temp_tar="${RUNNER_TEMP:-$(mktemp -d)}/task.tar.gz"
	if curl --proto '=https' \
		--tlsv1.2 \
		--fail \
		--silent \
		--show-error \
		--location \
		--connect-timeout 10 \
		--max-time 60 \
		--retry 2 \
		--retry-delay 3 \
		"${auth_args[@]}" \
		"$download_url" \
		--output "$temp_tar"; then

		if mkdir -p "$task_bin_dir" && tar -xzf "$temp_tar" -C "$task_bin_dir" task && [[ -x "$task_bin_dir/task" ]]; then
			echo "GitHub release download successful"
			rm -f "$temp_tar"
			return 0
		else
			echo "Failed to extract or verify Task binary" >&2
			rm -f "$temp_tar"
			return 1
		fi
	else
		echo "Failed to download from GitHub release" >&2
		return 1
	fi
}

install_task

if [[ ! -x "$task_bin_dir/task" ]]; then
	echo "Error: Task binary not found or not executable at $task_bin_dir/task" >&2
	exit 1
fi

echo "Task is ready at $task_bin_dir/task"
"$task_bin_dir/task" --version
echo "$task_bin_dir" >>"$GITHUB_PATH"
