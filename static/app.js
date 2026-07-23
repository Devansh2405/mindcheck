const chatWindow = document.getElementById("chat-window");
const composer = document.getElementById("composer");
const input = document.getElementById("user-input");
const sendBtn = document.getElementById("send-btn");

const history = []; // { role: "user" | "assistant", content: string }

function addBubble(role, text = "") {
  const msg = document.createElement("div");
  msg.className = `msg ${role}`;
  const bubble = document.createElement("div");
  bubble.className = "bubble";
  bubble.textContent = text;
  msg.appendChild(bubble);
  chatWindow.appendChild(msg);
  chatWindow.scrollTop = chatWindow.scrollHeight;
  return bubble;
}

function autoGrow() {
  input.style.height = "auto";
  input.style.height = Math.min(input.scrollHeight, 120) + "px";
}
input.addEventListener("input", autoGrow);

async function sendMessage(text) {
  history.push({ role: "user", content: text });
  addBubble("user", text);

  const assistantBubble = addBubble("assistant", "");
  let assistantText = "";

  sendBtn.disabled = true;

  try {
    const res = await fetch("/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ messages: history }),
    });

    if (!res.ok || !res.body) {
      throw new Error(`Request failed: ${res.status}`);
    }

    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";

    while (true) {
      const { value, done } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });

      const events = buffer.split("\n\n");
      buffer = events.pop(); // keep incomplete tail

      for (const evt of events) {
        const line = evt.replace(/^data: /, "").trim();
        if (!line) continue;
        if (line === "[DONE]") continue;

        try {
          const parsed = JSON.parse(line);
          if (parsed.delta) {
            assistantText += parsed.delta;
            assistantBubble.textContent = assistantText;
            chatWindow.scrollTop = chatWindow.scrollHeight;
          }
        } catch {
          // ignore malformed frame
        }
      }
    }

    history.push({ role: "assistant", content: assistantText });
  } catch (err) {
    assistantBubble.textContent =
      "Sorry, something went wrong reaching the assistant. Please try again.";
    console.error(err);
  } finally {
    sendBtn.disabled = false;
  }
}

composer.addEventListener("submit", (e) => {
  e.preventDefault();
  const text = input.value.trim();
  if (!text) return;
  input.value = "";
  autoGrow();
  sendMessage(text);
});

// Enter to send, Shift+Enter for newline
input.addEventListener("keydown", (e) => {
  if (e.key === "Enter" && !e.shiftKey) {
    e.preventDefault();
    composer.requestSubmit();
  }
});
