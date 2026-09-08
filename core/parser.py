import re

class StreamParser:
    def __init__(self):
        self.buffer = ""
        self.in_thought = False

    def process_chunk(self, chunk: str) -> list:
        self.buffer += chunk
        output = []

        while self.buffer:
            if not self.in_thought:
                idx = self.buffer.find("<think>")
                if idx != -1:
                    if idx > 0:
                        output.append((self.buffer[:idx], "agent"))
                    output.append(("\n🧠 [PROCES MYŚLENIA]:\n", "thought_header"))
                    self.in_thought = True
                    self.buffer = self.buffer[idx+7:]
                    continue

                # Check for partial match at the end
                partial = False
                for i in range(1, 7):
                    if self.buffer.endswith("<think>"[:i]):
                        if len(self.buffer) > i:
                            output.append((self.buffer[:-i], "agent"))
                        self.buffer = self.buffer[-i:]
                        partial = True
                        break

                if not partial:
                    output.append((self.buffer, "agent"))
                    self.buffer = ""
            else:
                idx = self.buffer.find("</think>")
                if idx != -1:
                    if idx > 0:
                        output.append((self.buffer[:idx], "thought"))
                    output.append(("\n" + "-"*40 + "\n", "thought_header"))
                    self.in_thought = False
                    self.buffer = self.buffer[idx+8:]
                    continue

                # Check for partial match at the end
                partial = False
                for i in range(1, 8):
                    if self.buffer.endswith("</think>"[:i]):
                        if len(self.buffer) > i:
                            output.append((self.buffer[:-i], "thought"))
                        self.buffer = self.buffer[-i:]
                        partial = True
                        break

                if not partial:
                    output.append((self.buffer, "thought"))
                    self.buffer = ""

        return output

def parse_model_output(raw_output: str):
    """Legacy parser for non-streaming output."""
    think_match = re.search(r'<think>(.*?)</think>', raw_output, re.DOTALL)
    thought_process = think_match.group(1).strip() if think_match else None
    clean_response = re.sub(r'<think>.*?</think>', '', raw_output, flags=re.DOTALL).strip()
    return thought_process, clean_response
