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
    is_anthropic = False
    match sys.argv[1]:
        case "flash":
            provider = "openrouter"
            model = "google/gemini-3-flash-preview"
        case "pro":
            provider = "openrouter"
            model = "google/gemini-3.1-pro-preview"
        case "opus":
            provider = "bedrock"
            model = "anthropic.claude-opus-4-7"
            is_anthropic = True
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
            api_url = "https://bedrock-mantle.us-east-1.api.aws/anthropic/v1/messages"

    with niquests.Session() as s:
        s.headers.update(
            {
                "Content-Type": "application/json",
                "Authorization": f"Bearer {api_key}",
            }
        )
        if is_anthropic:
            s.headers.update({"anthropic-version": "2023-06-01"})
        system_prompt_pieces = [
            "agentic code editor",
            "allowed to use bash tools, can write content to any file using the write tool",
            "you cannot write only part of a file, always write the whole file",
            "iterate by calling tools as needed until the task is fully complete, calling no tools gives control back to user",
            "in text responses to user, avoid conversational filler, pleasantries, flowery language",
            "keep text responses short, succinct, brief",
            "keep things simple simple simple",
        ]
        system_prompt = " ".join(system_prompt_pieces)

        # include agents.md files into context
        # for every line that starts with @ and has a valid filepath after it, include that in the context as well
        agents_md_path = Path("./agents.md")
        if agents_md_path.exists():
            system_prompt += "\n"
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
            system_prompt += "\n".join(expanded_lines)

        messages = []
        if not is_anthropic:
            messages = [
                {
                    "role": "system",
                    "content": system_prompt,
                },
            ]

        tools = None
        # Anthropic style
        if is_anthropic:
            tools = [
                {
                    "name": "bash",
                    "description": "Execute command in bash",
                    "input_schema": {
                        "type": "object",
                        "properties": {
                            "command": {"type": "string", "description": "Command"}
                        },
                        "required": ["command"],
                    },
                },
                {
                    "name": "write",
                    "description": "Write contents entirely to filepath",
                    "input_schema": {
                        "type": "object",
                        "properties": {
                            "filepath": {"type": "string"},
                            "contents": {"type": "string"},
                        },
                        "required": ["filepath", "contents"],
                    },
                },
            ]
        # OpenAI style
        else:
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

                    # Build payload
                    if is_anthropic:
                        payload = {
                            "model": model,
                            # max tokens is required parameter for some reason
                            # 128,000 is the maximum max_tokens
                            "max_tokens": 128_000,
                            "system": system_prompt,
                            "messages": messages,
                            "tools": tools,
                        }
                    else:
                        payload = {"model": model, "messages": messages, "tools": tools}
                    r = s.post(
                        api_url,
                        json=payload,
                    )
                    r.raise_for_status()
                    response = r.json()

                    sys.stdout.write(
                        "\r\033[2K"
                    )  # after \r is the terminal code to erase entire current line
                    turn += 1
                    print(f"{purple}[trn]{reset} {turn}")

                    txt: str | None = None
                    tool_calls = []
                    if is_anthropic:
                        for block in response["content"]:
                            match block["type"]:
                                case "text":
                                    txt = block["text"]
                                case "tool_use":
                                    tool_calls.append(block)
                        messages.append(
                            {"role": "assistant", "content": response["content"]}
                        )
                        if txt is not None:
                            print(f"{purple}[txt]{reset}", txt)
                    else:
                        ai_message = response["choices"][0]["message"]
                        txt = ai_message["content"]
                        if txt is not None:
                            messages.append({"role": "assistant", "content": txt})
                            print(f"{purple}[txt]{reset}", txt)

                    # it has to be nested, otherwise on anthropic calls with no tool calls it will check for tool_calls in ai_message
                    if is_anthropic:
                        if len(tool_calls) == 0:
                            break
                    else:
                        if "tool_calls" not in ai_message:
                            break
                        else:
                            tool_calls = ai_message["tool_calls"]

                    # Keep track if a tool fails so we skip remaining tools in the batch
                    skip_remaining = False

                    if is_anthropic:
                        tool_results = []  # collect all for the anthropic style
                    for tool_call in tool_calls:
                        tool_call_id = tool_call["id"]
                        if is_anthropic:
                            function_name = tool_call["name"]
                            arguments = tool_call["input"]
                        else:
                            function_name = tool_call["function"]["name"]
                            arguments = orjson.loads(tool_call["function"]["arguments"])

                        def record_result(content: str):
                            if is_anthropic:
                                tool_results.append(
                                    {
                                        "type": "tool_result",
                                        "tool_use_id": tool_call_id,
                                        "content": content,
                                    }
                                )
                            else:
                                messages.append(
                                    {
                                        "role": "tool",
                                        "tool_call_id": tool_call_id,
                                        "name": function_name,
                                        "content": content,
                                    }
                                )

                        if skip_remaining:
                            record_result(
                                "Skipped: previous tool in batch returned non-zero exit code"
                            )
                            continue

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

                            record_result(output_msg)

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
                                record_result(f"Successfully wrote to {filepath}")
                            except Exception as e:
                                error_msg = f"file write error {filepath}: {str(e)}"
                                print(f"{purple}[wrt] [errr]{reset}", str(e))
                                record_result(error_msg)
                                skip_remaining = True

                    if is_anthropic and tool_results:
                        messages.append({"role": "user", "content": tool_results})

            except KeyboardInterrupt, EOFError:
                print("\nExiting...", file=sys.stderr)
                break
