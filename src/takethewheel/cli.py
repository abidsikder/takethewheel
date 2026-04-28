import os
import subprocess
import sys
from pathlib import Path
from typing import Literal

import niquests
import orjson  # comes with niquests

purple = "\033[35m"
reset = "\033[0m"


def cli():
    provider: Literal["openrouter", "bedrock"] | None = None
    model: str | None = None
    match sys.argv[1]:
        case "flash":
            provider = "openrouter"
            model = "google/gemini-3-flash-preview"
        case "pro":
            provider = "openrouter"
            model = "google/gemini-3.1-pro-preview"
        case "glm":
            provider = "bedrock"
            model = "zai.glm-5"
        case _:
            print("Improper argument", file=sys.stderr)
            sys.exit(1)

    api_key: str | None = None
    api_url: str | None = None
    match provider:
        case "openrouter":
            api_key = os.environ["OPENROUTER_API_KEY"]
            api_url = "https://openrouter.ai/api/v1/chat/completions"
        case "bedrock":
            api_key = os.environ["AWS_BEARER_TOKEN_BEDROCK"]
            api_url = "https://bedrock-mantle.us-east-1.api.aws/v1/chat/completions"

    with niquests.Session() as s:
        s.headers.update(
            {
                "Authorization": f"Bearer {api_key}",
            }
        )
        system_prompt_pieces = [
            "agentic code editor",
            "allowed to use bash tools, can write content to any file using the write tool",
            "you cannot write only part of a file, always write the whole file",
            "iterate by calling tools as needed until the task is fully complete, calling no tools gives control back to user",
            "in text responses to user, avoid conversational filler, pleasantries, flowery language",
            "keep text responses short, succinct, brief",
            "keep things simple simple simple",
        ]
        messages = [
            {
                "role": "system",
                "content": " ".join(system_prompt_pieces),
            },
        ]

        # include agents.md files into context
        # for every line that starts with @ and has a valid filepath after it, include that in the context as well
        agents_md_path = Path("./agents.md")
        if agents_md_path.exists():
            messages[0]["content"] += "\n"
            expanded_lines = []
            for line in agents_md_path.read_text().splitlines():
                if line and line[0] == "@":
                    filepath = Path(line[1:].strip()).resolve()
                    if not filepath.exists():
                        raise FileNotFoundError(f"Included file not found: {filepath}")
                    expanded_lines.append(str(filepath))
                    expanded_lines.append(filepath.read_text())
                else:
                    expanded_lines.append(line)
            messages[0]["content"] += "\n".join(expanded_lines)

        tools = [
            {
                "type": "function",
                "function": {
                    "name": "bash",
                    "description": "Execute command in bash",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "command": {"type": "string", "description": "Command"}
                        },
                        "required": ["command"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "write",
                    "description": "Write contents entirely to filepath",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "filepath": {"type": "string"},
                            "contents": {"type": "string"},
                        },
                        "required": ["filepath", "contents"],
                    },
                },
            },
        ]

        print("Press Ctrl-C or Ctrl-D to exit", file=sys.stderr)
        turn = 0
        user_prompt_line = f"{purple}> {reset}"
        while True:
            try:
                user_input = input(user_prompt_line)
                messages.append({"role": "user", "content": user_input})

                # ====== Agent Inner Loop ======
                while True:
                    sys.stdout.write(f"{purple}Communicating with AI service...{reset}")
                    sys.stdout.flush()
                    r = s.post(
                        api_url,
                        json={
                            "model": model,
                            "messages": messages,
                            "tools": tools,
                            "tool_choice": "auto",
                        },
                    )
                    r.raise_for_status()
                    response = r.json()

                    sys.stdout.write(
                        "\r\033[2K"
                    )  # after \r is the terminal code to erase entire current line
                    turn += 1
                    print(f"{purple}[trn]{reset} {turn}")

                    ai_message = response["choices"][0]["message"]
                    txt = ai_message["content"]
                    if txt is not None:
                        messages.append({"role": "assistant", "content": txt})
                        print(f"{purple}[txt]{reset}", txt)

                    if "tool_calls" not in ai_message:
                        break

                    # Keep track if a tool fails so we skip remaining tools in the batch
                    skip_remaining = False

                    for tool_call in ai_message["tool_calls"]:
                        tool_call_id = tool_call["id"]
                        function_name = tool_call["function"]["name"]
                        if skip_remaining:
                            messages.append(
                                {
                                    "role": "tool",
                                    "tool_call_id": tool_call_id,
                                    "name": function_name,
                                    "content": "Skipped: previous tool in batch returned non-zero exit code",
                                }
                            )
                            continue

                        arguments = orjson.loads(tool_call["function"]["arguments"])

                        if function_name == "bash":
                            cmd = arguments["command"]
                            print(f"{purple}[cmd]{reset} {cmd}")

                            result = subprocess.run(
                                cmd, shell=True, capture_output=True, text=True
                            )

                            stdout = result.stdout.strip()
                            stderr = result.stderr.strip()
                            exit_code = result.returncode

                            print(f"{purple}[cmd] [stdout]{reset}")
                            if stdout:
                                print(stdout)
                            if stderr:
                                print(f"{purple}[cmd] [stderr]{reset}")
                                print(stderr)

                            output_msg = f"exit_code: {exit_code}\nstdout:\n{stdout}"
                            if stderr:
                                output_msg += f"\nstderr:\n{stderr}"

                            messages.append(
                                {
                                    "role": "tool",
                                    "tool_call_id": tool_call_id,
                                    "name": function_name,
                                    "content": output_msg,
                                }
                            )

                            if exit_code != 0:
                                skip_remaining = True  # Stop executing subsequent commands in this batch

                        elif function_name == "write":
                            filepath = arguments["filepath"]
                            contents = arguments["contents"]
                            print(f"{purple}[wrt] [path]{reset}", filepath)
                            print(f"{purple}[wrt] [text]{reset}\n{contents}\n")

                            try:
                                Path(filepath).parent.mkdir(parents=True, exist_ok=True)
                                Path(filepath).write_text(contents)
                                messages.append(
                                    {
                                        "role": "tool",
                                        "tool_call_id": tool_call_id,
                                        "name": function_name,
                                        "content": f"Successfully wrote to {filepath}",
                                    }
                                )
                            except Exception as e:
                                error_msg = f"file write error {filepath}: {str(e)}"
                                print(f"{purple}[wrt] [errr]{reset}", str(e))
                                messages.append(
                                    {
                                        "role": "tool",
                                        "tool_call_id": tool_call_id,
                                        "name": function_name,
                                        "content": error_msg,
                                    }
                                )
                                skip_remaining = True

            except KeyboardInterrupt, EOFError:
                print("\nExiting...", file=sys.stderr)
                break
