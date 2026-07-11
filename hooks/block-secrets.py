"""
PreToolUse hook: Block access to sensitive files and environment variables.

Intercepts Read, Bash, Grep, Edit, and Write tool calls to prevent API keys,
tokens, and credentials from entering the LLM context window.

Exit codes:
  0 = allow (tool proceeds normally)
  2 = block (stderr shown to Claude as feedback)
"""

import json
import re
import sys

# --- Sensitive file patterns ---
# Any file path matching these patterns should never be read or written by the LLM
SENSITIVE_FILE_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"\.env($|\.)", re.IGNORECASE),           # .env, .env.local, .env.production
    re.compile(r"\.pem$", re.IGNORECASE),                 # SSL/TLS certificates
    re.compile(r"\.key$", re.IGNORECASE),                 # Private keys
    re.compile(r"google_credentials\.json", re.IGNORECASE),  # OAuth client secret
    re.compile(r"google_token\.json", re.IGNORECASE),     # OAuth refresh token
    re.compile(r"credentials\.json", re.IGNORECASE),      # Generic credentials
    re.compile(r"\.credentials\.json", re.IGNORECASE),    # Claude credentials
    re.compile(r"master\.env", re.IGNORECASE),            # Master env file
    re.compile(r"\.ssh/", re.IGNORECASE),                 # SSH keys directory
    re.compile(r"id_rsa", re.IGNORECASE),                 # SSH private key
    re.compile(r"id_ed25519", re.IGNORECASE),             # SSH private key (ed25519)
    re.compile(r"\.aws/credentials", re.IGNORECASE),      # AWS credentials
    re.compile(r"\.netrc", re.IGNORECASE),                # Network credentials
    re.compile(r"secret", re.IGNORECASE),                 # Files with "secret" in the name
]

# Exclude false positives for "secret" pattern - these are safe to read
SECRET_FALSE_POSITIVES: list[re.Pattern[str]] = [
    re.compile(r"\.md$", re.IGNORECASE),          # Markdown docs discussing secrets
    re.compile(r"\.py$", re.IGNORECASE),           # Python code (may reference but not contain)
    re.compile(r"\.ts$", re.IGNORECASE),           # TypeScript code
    re.compile(r"\.js$", re.IGNORECASE),           # JavaScript code
    re.compile(r"\.txt$", re.IGNORECASE),          # Text files
    re.compile(r"\.yml$", re.IGNORECASE),          # YAML config
    re.compile(r"\.yaml$", re.IGNORECASE),         # YAML config
    re.compile(r"\.toml$", re.IGNORECASE),         # TOML config
    re.compile(r"\.example$", re.IGNORECASE),      # Example files (.env.example)
]


def is_sensitive_file(path: str) -> str | None:
    """Check if a file path matches a sensitive pattern. Returns the reason or None."""
    for pattern in SENSITIVE_FILE_PATTERNS:
        if pattern.search(path):
            # Special handling for "secret" - allow code/docs that discuss secrets
            if pattern.pattern == "secret":
                for fp in SECRET_FALSE_POSITIVES:
                    if fp.search(path):
                        return None
                # Also allow .env.example files
                if ".example" in path.lower():
                    return None
            # Allow .env.example explicitly
            if ".env.example" in path.lower() or ".env.sample" in path.lower():
                return None
            return f"Blocked: '{path}' matches sensitive file pattern '{pattern.pattern}'"
    return None


# --- Dangerous bash patterns for env/secret exposure ---
DANGEROUS_BASH_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    # Direct .env file reads
    (re.compile(r"\bcat\b.*\.env\b", re.IGNORECASE), "Reading .env file with cat"),
    (re.compile(r"\bhead\b.*\.env\b", re.IGNORECASE), "Reading .env file with head"),
    (re.compile(r"\btail\b.*\.env\b", re.IGNORECASE), "Reading .env file with tail"),
    (re.compile(r"\bless\b.*\.env\b", re.IGNORECASE), "Reading .env file with less"),
    (re.compile(r"\bmore\b.*\.env\b", re.IGNORECASE), "Reading .env file with more"),
    (re.compile(r"\btype\b.*\.env\b", re.IGNORECASE), "Reading .env file with type"),
    (re.compile(r"\bbat\b.*\.env\b", re.IGNORECASE), "Reading .env file with bat"),
    (re.compile(r"\bvi\b.*\.env\b", re.IGNORECASE), "Opening .env file in editor"),
    (re.compile(r"\bvim\b.*\.env\b", re.IGNORECASE), "Opening .env file in editor"),
    (re.compile(r"\bnano\b.*\.env\b", re.IGNORECASE), "Opening .env file in editor"),
    (re.compile(r"\bcode\b.*\.env\b", re.IGNORECASE), "Opening .env file in editor"),
    (re.compile(r"\bsource\b.*\.env\b", re.IGNORECASE), "Sourcing .env file"),
    (re.compile(r"\.\s+.*\.env\b", re.IGNORECASE), "Sourcing .env with dot notation"),

    # Credential file reads
    (re.compile(r"\bcat\b.*credentials", re.IGNORECASE), "Reading credentials file"),
    (re.compile(r"\bcat\b.*google_token", re.IGNORECASE), "Reading Google token file"),
    (re.compile(r"\bcat\b.*\.pem\b", re.IGNORECASE), "Reading certificate file"),
    (re.compile(r"\bcat\b.*\.key\b", re.IGNORECASE), "Reading key file"),
    (re.compile(r"\bcat\b.*id_rsa", re.IGNORECASE), "Reading SSH private key"),
    (re.compile(r"\bcat\b.*id_ed25519", re.IGNORECASE), "Reading SSH private key"),
    (re.compile(r"\bcat\b.*\.ssh/", re.IGNORECASE), "Reading SSH directory file"),
    (re.compile(r"\bcat\b.*master\.env", re.IGNORECASE), "Reading master env file"),

    # Environment variable printing
    (re.compile(r"\bprintenv\b", re.IGNORECASE), "Printing environment variables"),
    (re.compile(r"\benv\b\s*$", re.IGNORECASE), "Listing all environment variables"),
    (re.compile(r"\benv\b\s*\|", re.IGNORECASE), "Piping environment variables"),
    (re.compile(r"\bset\b\s*\|", re.IGNORECASE), "Piping shell variables"),
    (re.compile(r"\bexport\s+-p\b", re.IGNORECASE), "Listing exported variables"),
    (re.compile(r"\bdeclare\s+-x\b", re.IGNORECASE), "Listing exported variables"),
    (re.compile(r"\bcompgen\s+-v\b", re.IGNORECASE), "Listing all variable names"),

    # Echo/printf of specific secret-like variables
    (re.compile(r"\becho\b.*\$.*(?:KEY|TOKEN|SECRET|PASSWORD|CREDENTIAL|API_KEY|ACCESS_TOKEN|AUTH)", re.IGNORECASE),
     "Echoing secret environment variable"),
    (re.compile(r"\bprintf\b.*\$.*(?:KEY|TOKEN|SECRET|PASSWORD|CREDENTIAL|API_KEY|ACCESS_TOKEN|AUTH)", re.IGNORECASE),
     "Printf of secret environment variable"),

    # Python inline execution that accesses env vars
    (re.compile(r"python[3]?\s+-c\s+.*os\.environ", re.IGNORECASE),
     "Python inline code accessing os.environ"),
    (re.compile(r"python[3]?\s+-c\s+.*os\.getenv", re.IGNORECASE),
     "Python inline code accessing os.getenv"),
    (re.compile(r"python[3]?\s+-c\s+.*dotenv", re.IGNORECASE),
     "Python inline code loading dotenv"),
    (re.compile(r"python[3]?\s+-c\s+.*\.env", re.IGNORECASE),
     "Python inline code referencing .env"),
    (re.compile(r"python[3]?\s+-c\s+.*open\(.*\.env", re.IGNORECASE),
     "Python inline code opening .env"),

    # Node inline execution
    (re.compile(r"node\s+-e\s+.*process\.env", re.IGNORECASE),
     "Node inline code accessing process.env"),

    # Other interpreter inline execution
    (re.compile(r"\bruby\s+-e\b.*ENV", re.IGNORECASE),
     "Ruby inline code accessing ENV"),
    (re.compile(r"\bperl\s+-e\b.*ENV", re.IGNORECASE),
     "Perl inline code accessing %ENV"),
    (re.compile(r"\bphp\s+-r\b.*getenv", re.IGNORECASE),
     "PHP inline code accessing getenv"),

    # Grep/search targeting sensitive files
    (re.compile(r"\bgrep\b.*\.env\b", re.IGNORECASE), "Grep searching .env file"),
    (re.compile(r"\brg\b.*\.env\b", re.IGNORECASE), "Ripgrep searching .env file"),
    (re.compile(r"\bfind\b.*\.env\b", re.IGNORECASE), "Find searching for .env files"),
    (re.compile(r"\bfind\b.*-exec\b.*cat", re.IGNORECASE), "Find with exec cat (potential .env read)"),

    # Wildcard bypass: cat .en* or cat .e?? could match .env
    (re.compile(r"\bcat\b.*\.en\*", re.IGNORECASE), "Wildcard read that could match .env"),
    (re.compile(r"\bcat\b.*\.e\?\?", re.IGNORECASE), "Wildcard read that could match .env"),
    (re.compile(r"\bcat\b.*\.e\[", re.IGNORECASE), "Glob pattern read that could match .env"),

    # Symlink creation targeting sensitive files
    (re.compile(r"\bln\b.*-s.*\.env\b", re.IGNORECASE), "Creating symlink to .env file"),
    (re.compile(r"\bln\b.*-s.*credentials", re.IGNORECASE), "Creating symlink to credentials"),
    (re.compile(r"\bln\b.*-s.*google_token", re.IGNORECASE), "Creating symlink to token file"),
    (re.compile(r"\bcp\b.*\.env\b", re.IGNORECASE), "Copying .env file"),

    # Here-doc/here-string execution with env access
    (re.compile(r"python[3]?\s*<<", re.IGNORECASE),
     "Python here-doc execution (could access env vars)"),
    (re.compile(r"\bperl\b\s*<<", re.IGNORECASE),
     "Perl here-doc execution (could access env vars)"),
    (re.compile(r"\bruby\b\s*<<", re.IGNORECASE),
     "Ruby here-doc execution (could access env vars)"),

    # Base64 decoding piped to execution (common bypass technique)
    (re.compile(r"base64\s+(-d|--decode).*\|\s*(sh|bash|zsh|python|ruby|perl|node)", re.IGNORECASE),
     "Base64 decoded command piped to interpreter"),
    (re.compile(r"bash\s*<<<.*base64", re.IGNORECASE),
     "Base64 here-string piped to bash"),

    # Variable expansion bypass: cat .e${IFS}nv, cat .e$()nv
    (re.compile(r"\bcat\b.*\.e\$", re.IGNORECASE), "Variable expansion bypass targeting .env"),
    (re.compile(r"\bcat\b.*\.e\\", re.IGNORECASE), "Backslash bypass targeting .env"),

    # Eval with env/secret references (not all eval - ssh-agent etc. are legitimate)
    (re.compile(r"\beval\b.*\.env", re.IGNORECASE), "Eval referencing .env file"),
    (re.compile(r"\beval\b.*\$.*(?:KEY|TOKEN|SECRET|PASSWORD|CREDENTIAL)", re.IGNORECASE),
     "Eval referencing secret variable"),
    (re.compile(r"\beval\b.*os\.environ", re.IGNORECASE), "Eval accessing os.environ"),
    (re.compile(r"\bexec\b\s+\d*[<>]", re.IGNORECASE), "Exec with file descriptor redirect"),

    # Curl/wget exfiltration of env data
    (re.compile(r"\bcurl\b.*\$.*(?:KEY|TOKEN|SECRET|PASSWORD)", re.IGNORECASE),
     "Curl with secret variable in URL/data"),
    (re.compile(r"\bwget\b.*\$.*(?:KEY|TOKEN|SECRET|PASSWORD)", re.IGNORECASE),
     "Wget with secret variable in URL/data"),
    # Broader exfiltration: curl/wget posting file contents
    (re.compile(r"\bcurl\b.*-d\s*@.*\.env", re.IGNORECASE),
     "Curl posting .env file contents"),
    (re.compile(r"\bcurl\b.*--data.*\.env", re.IGNORECASE),
     "Curl posting .env file contents"),

    # Process substitution reading sensitive files
    (re.compile(r"<\(.*cat.*\.env", re.IGNORECASE), "Process substitution reading .env"),
    (re.compile(r"<\(.*\.env", re.IGNORECASE), "Process substitution referencing .env"),

    # xxd/hexdump of sensitive files (binary dump to bypass text filters)
    (re.compile(r"\bxxd\b.*\.env", re.IGNORECASE), "Hex dump of .env file"),
    (re.compile(r"\bhexdump\b.*\.env", re.IGNORECASE), "Hex dump of .env file"),
    (re.compile(r"\bod\b.*\.env", re.IGNORECASE), "Octal dump of .env file"),

    # xargs execution that could target sensitive files
    (re.compile(r"\bxargs\b.*cat", re.IGNORECASE), "xargs with cat (potential .env read)"),
]


def check_bash_command(command: str) -> str | None:
    """Check if a bash command would expose secrets. Returns the reason or None."""
    # Normalize: collapse whitespace, strip
    normalized = " ".join(command.split()).strip()

    for pattern, reason in DANGEROUS_BASH_PATTERNS:
        if pattern.search(normalized):
            return f"Blocked: {reason}"

    # Also check for subshell content: $(...) and `...`
    # Extract subshell commands and check them recursively
    subshell_patterns = [
        re.compile(r"\$\((.*?)\)", re.DOTALL),   # $(...)
        re.compile(r"`(.*?)`", re.DOTALL),         # `...`
    ]
    for sp in subshell_patterns:
        for match in sp.finditer(normalized):
            inner = match.group(1)
            result = check_bash_command(inner)
            if result:
                return f"{result} (inside subshell)"

    return None


# --- Two-step attack: content patterns that would exfiltrate secrets ---
# These patterns detect when a script is being WRITTEN that would print/expose env vars.
# We allow scripts that USE env vars (e.g., load_dotenv() + os.getenv for API calls)
# but block scripts that PRINT/LOG/RETURN them to stdout where Claude would see them.
EXFILTRATION_CONTENT_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    # Python: printing env vars
    (re.compile(r"print\s*\(.*os\.environ", re.IGNORECASE),
     "Script prints os.environ to stdout"),
    (re.compile(r"print\s*\(.*os\.getenv\s*\(", re.IGNORECASE),
     "Script prints os.getenv() to stdout"),
    (re.compile(r"print\s*\(.*\.env", re.IGNORECASE),
     "Script prints .env content to stdout"),
    (re.compile(r"json\.dumps?\s*\(.*os\.environ", re.IGNORECASE),
     "Script serializes os.environ to JSON"),
    (re.compile(r"sys\.stdout\.write.*os\.environ", re.IGNORECASE),
     "Script writes os.environ to stdout"),
    (re.compile(r"pprint.*os\.environ", re.IGNORECASE),
     "Script pretty-prints os.environ"),

    # Python: reading .env and printing
    (re.compile(r"open\s*\(.*\.env.*\).*read\(\)", re.IGNORECASE),
     "Script reads .env file contents"),

    # Bash script: cat/echo env vars
    (re.compile(r"cat\s+.*\.env", re.IGNORECASE),
     "Script cats .env file"),
    (re.compile(r"echo\s+\$\{?[A-Z_]*(?:KEY|TOKEN|SECRET|PASSWORD|CREDENTIAL)", re.IGNORECASE),
     "Script echoes secret variable"),
    (re.compile(r"printenv", re.IGNORECASE),
     "Script runs printenv"),

    # Ruby/Perl/Node
    (re.compile(r"puts\s+ENV", re.IGNORECASE), "Script prints Ruby ENV"),
    (re.compile(r"print\s+%ENV", re.IGNORECASE), "Script prints Perl %ENV"),
    (re.compile(r"console\.log\s*\(\s*process\.env", re.IGNORECASE), "Script logs process.env"),

    # Curl/wget exfiltration in script
    (re.compile(r"curl.*\$\{?[A-Z_]*(?:KEY|TOKEN|SECRET|PASSWORD)", re.IGNORECASE),
     "Script exfiltrates secret via curl"),
    (re.compile(r"requests\.(get|post).*os\.getenv", re.IGNORECASE),
     "Script sends env var via HTTP request"),
]


def check_written_content(content: str) -> str | None:
    """Check if file content being written would exfiltrate secrets."""
    if not content:
        return None
    for pattern, reason in EXFILTRATION_CONTENT_PATTERNS:
        if pattern.search(content):
            return f"Blocked: {reason} — writing scripts that expose secrets is not allowed"
    return None


def main() -> None:
    try:
        hook_input = json.load(sys.stdin)
    except json.JSONDecodeError:
        print("Failed to parse hook input JSON", file=sys.stderr)
        sys.exit(1)

    tool_name = hook_input.get("tool_name", "")
    tool_input = hook_input.get("tool_input", {})

    reason: str | None = None

    if tool_name == "Read":
        file_path = tool_input.get("file_path", "")
        reason = is_sensitive_file(file_path)

    elif tool_name == "Bash":
        command = tool_input.get("command", "")
        reason = check_bash_command(command)

    elif tool_name == "Grep":
        path = tool_input.get("path", "")
        pattern = tool_input.get("pattern", "")
        if path:
            reason = is_sensitive_file(path)
        # Also check if grepping for secret patterns in a way that would expose values
        if not reason and re.search(r"\.env", path or "", re.IGNORECASE):
            reason = "Blocked: Grep targeting .env file"

    elif tool_name in ("Edit", "Write"):
        file_path = tool_input.get("file_path", "")
        reason = is_sensitive_file(file_path)
        # Two-step attack defense: check if content being written would
        # create a script that prints/exfiltrates environment variables
        if not reason:
            content = tool_input.get("content", "") or tool_input.get("new_string", "")
            reason = check_written_content(content)

    elif tool_name == "Glob":
        pattern_str = tool_input.get("pattern", "")
        if re.search(r"\.env", pattern_str, re.IGNORECASE):
            reason = "Blocked: Glob pattern targeting .env files"

    if reason:
        print(
            f"SECURITY: {reason}. "
            "API keys and credentials must never enter the context window. "
            "Use the Python CLI wrapper (query.py) to interact with integrations instead.",
            file=sys.stderr,
        )
        sys.exit(2)

    # Allow the tool call
    sys.exit(0)


if __name__ == "__main__":
    main()
