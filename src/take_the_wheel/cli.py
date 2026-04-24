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
            "allowed to use bash, can write content to any desired file",
            "do not write only part of file, always write the whole file",
            "decide when finished working with done flag, if done is False then we will keep iterating",
            "when done, give text response back to user",
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
        agents_md_path = Path("./AGENTS.md")
        if agents_md_path.exists():
            messages[0]["content"] += "\n"
            expanded_lines = []
            for line in agents_md_path.read_text().splitlines():
                if line[0] == "@":
                    filepath = Path(line[1:].strip()).resolve()
                    if not filepath.exists():
                        raise FileNotFoundError(f"Included file not found: {filepath}")
                    expanded_lines.append(str(filepath))
                    expanded_lines.append(filepath.read_text())
                else:
                    expanded_lines.append(line)
            messages[0]["content"] += "\n".join(expanded_lines)

        response_schema = {
            "type": "object",
            "properties": {
                "txt": {
                    "type": "string",
                    "description": "messages to the user",
                },
                "actions": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "bash": {
                                "type": "string",
                                "description": "bash command to execute",
                            },
                            "write": {
                                "type": "object",
                                "properties": {
                                    "filepath": {"type": "string"},
                                    "contents": {"type": "string"},
                                },
                                "required": ["filepath", "contents"],
                            },
                        },
                    },
                },
                "done": {
                    "type": "boolean",
                    "description": "Is task complete",
                },
            },
            "required": ["txt", "actions", "done"],
        }
        print("Press Ctrl-C or Ctrl-D to exit", file=sys.stderr)
        turn = 0
        user_prompt_line = f"{purple}> {reset}"
        while True:
            try:
                user_input = input(user_prompt_line)
                messages.append({"role": "user", "content": user_input})

                # ====== Agent Inner Loop ======
                done = False
                while not done:
                    sys.stdout.write(f"{purple}Communicating with AI service...{reset}")
                    sys.stdout.flush()
                    r = s.post(
                        api_url,
                        json={
                            "model": model,
                            "messages": messages,
                            "response_format": {
                                "type": "json_schema",
                                "json_schema": {
                                    "name": "agent_action_schema",
                                    "strict": True,
                                    "schema": response_schema,
                                },
                            },
                        },
                    )
                    r.raise_for_status()
                    response = r.json()

                    ai_content_s = response["choices"][0]["message"]["content"]
                    ai_content = orjson.loads(ai_content_s)

                    txt = ai_content["txt"]
                    actions = ai_content["actions"]
                    done = ai_content["done"]

                    sys.stdout.write(
                        "\r\033[2K"
                    )  # after \r is the terminal code to erase entire current line
                    turn += 1
                    print(f"{purple}[trn]{reset} {turn}")

                    print(f"{purple}[txt]{reset}", txt)
                    messages.append({"role": "assistant", "content": txt})
                    for action in actions:
                        if "bash" in action:
                            cmd = action["bash"]
                            print(f"{purple}[cmd]{reset} {cmd}")

                            # Using shell=True to support pipes and general bash syntax
                            result = subprocess.run(
                                cmd, shell=True, capture_output=True, text=True
                            )

                            stdout = result.stdout.strip()
                            stderr = result.stderr.strip()
                            exit_code = result.returncode

                            print(f"{purple}[cmd] [stdout]{reset}")
                            print(stdout)
                            if stderr:
                                print(f"{purple}[cmd] [stderr]{reset}")
                                print(stderr)
                            output_msg = f"{cmd=} {exit_code=} {stdout=}"
                            if stderr:
                                output_msg += f"{stderr=}"
                            messages.append({"role": "user", "content": output_msg})

                            if exit_code != 0:
                                break  # Stop executing subsequent commands in this batch
                        elif "write" in action:
                            filepath = action["write"]["filepath"]
                            contents = action["write"]["contents"]
                            print(f"{purple}[wrt] [path]{reset}", filepath)
                            print(f"{purple}[wrt] [text]{reset}")
                            print(contents)

                            try:
                                Path(filepath).parent.mkdir(parents=True, exist_ok=True)
                                Path(filepath).write_text(contents)
                            except Exception as e:
                                error_msg = f"file write error {filepath}: {str(e)}"
                                messages.append({"role": "user", "content": error_msg})
                                print(f"{purple}[wrt] [errr]{reset}", str(e))
                                break  # Stop executing subsequent commands in this batch

            except KeyboardInterrupt, EOFError:
                print("\nExiting...", file=sys.stderr)
                break
