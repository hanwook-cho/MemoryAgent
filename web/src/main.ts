const API = "/api/v1";
const TOKEN_KEY = "memoryagent.apiToken";
const WELCOME_DISMISSED = "memoryagent.chatWelcome.dismissed";
const WELCOME_VERSION = "memoryagent.chatWelcome.version";
const SPEC_WELCOME_VERSION = "3";

const WELCOME_INTRO =
  "Hi — I'm **MemoryAgent**, your **private memory assistant on this Mac**. I help you remember what you save and answer questions using **your** stored information—with **sources** when I rely on memory—while keeping **your data on your device** by default.";

const WELCOME_DETAIL = `**What I can help with**

- **Save facts** — Tell me things to remember in chat ("Remember that …"), use quick entry, paste, or the memory controls below when available.
- **Ask questions** — I search what you've saved and reply in plain language; I'll point to **what I used** when citations are available.
- **Schedule on your calendar** — With your permission, you can ask me to **add an event** to your Calendar (I'll confirm the time when possible). For places you use often (e.g. dentist), I can **reuse the address** from a past visit or your saved notes when you don't type it.
- **Work offline** — Core chat is designed to run **locally** on your Mac without needing a cloud AI service for normal use.
- **Connect what you allow** — Over time you can let me use **folders you choose** and, with permission, **Calendar/Reminders**. I don't silently read your entire Mac.

**Good prompts to try** — "What have I saved about [topic]?", "Remember: [something important].", "Put [title] on my calendar [day] at [time]."`;

type Msg = { role: "user" | "assistant"; content: string; citations?: { chunk_id: string; snippet: string; score: number }[] };
type AppConfig = {
  watched_roots: string[];
  watch_ignore_globs: string[];
  watch_debounce_seconds: number;
};

function el(html: string): HTMLElement {
  const t = document.createElement("template");
  t.innerHTML = html.trim();
  return t.content.firstElementChild as HTMLElement;
}

function getToken(): string {
  return localStorage.getItem(TOKEN_KEY)?.trim() ?? "";
}

function shouldShowWelcome(): boolean {
  const dismissed = localStorage.getItem(WELCOME_DISMISSED) === "true";
  const ver = localStorage.getItem(WELCOME_VERSION) ?? "";
  if (!dismissed) return true;
  if (ver !== SPEC_WELCOME_VERSION) return true;
  return false;
}

function dismissWelcome(): void {
  localStorage.setItem(WELCOME_DISMISSED, "true");
  localStorage.setItem(WELCOME_VERSION, SPEC_WELCOME_VERSION);
}

function simpleMarkdown(s: string): string {
  return s
    .replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>")
    .replace(/\n/g, "<br/>");
}

async function apiChat(messages: Msg[], token: string): Promise<{ reply: string; citations: Msg["citations"] }> {
  const r = await fetch(`${API}/chat`, {
    method: "POST",
    headers: {
      Authorization: `Bearer ${token}`,
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      messages: messages.map((m) => ({ role: m.role, content: m.content })),
    }),
  });
  if (!r.ok) throw new Error(`chat ${r.status}`);
  const j = (await r.json()) as { reply: string; citations: NonNullable<Msg["citations"]> };
  return { reply: j.reply, citations: j.citations };
}

async function apiMirrorGet(mirrorId: string, token: string): Promise<{ content: string }> {
  const r = await fetch(`${API}/mirror/${mirrorId}`, {
    headers: { Authorization: `Bearer ${token}` },
  });
  if (!r.ok) throw new Error(`mirror get ${r.status}`);
  return (await r.json()) as { content: string };
}

async function apiMirrorPut(mirrorId: string, content: string, token: string): Promise<void> {
  const r = await fetch(`${API}/mirror/${mirrorId}`, {
    method: "PUT",
    headers: {
      Authorization: `Bearer ${token}`,
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ content }),
  });
  if (!r.ok) {
    let msg = `mirror save ${r.status}`;
    try {
      const j = (await r.json()) as {
        detail?: { error?: { message?: string } } | string;
      };
      const d = j.detail;
      if (typeof d === "object" && d?.error?.message) msg = d.error.message;
    } catch {
      /* ignore */
    }
    throw new Error(msg);
  }
}

async function apiMemory(text: string, token: string): Promise<void> {
  const r = await fetch(`${API}/memory/entries`, {
    method: "POST",
    headers: {
      Authorization: `Bearer ${token}`,
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ text, tags: [], source: "web_ui" }),
  });
  if (!r.ok) throw new Error(`memory ${r.status}`);
}

async function apiConfigGet(token: string): Promise<AppConfig> {
  const r = await fetch(`${API}/config`, {
    headers: { Authorization: `Bearer ${token}` },
  });
  if (!r.ok) throw new Error(`config get ${r.status}`);
  return (await r.json()) as AppConfig;
}

async function apiConfigPatch(token: string, body: Partial<AppConfig>): Promise<AppConfig> {
  const r = await fetch(`${API}/config`, {
    method: "PATCH",
    headers: {
      Authorization: `Bearer ${token}`,
      "Content-Type": "application/json",
    },
    body: JSON.stringify(body),
  });
  if (!r.ok) {
    let msg = `config patch ${r.status}`;
    try {
      const j = (await r.json()) as { detail?: { error?: { message?: string } } | string };
      const d = j.detail;
      if (typeof d === "object" && d?.error?.message) msg = d.error.message;
    } catch {
      /* ignore */
    }
    throw new Error(msg);
  }
  return (await r.json()) as AppConfig;
}

async function apiPickFolder(token: string): Promise<string> {
  const r = await fetch(`${API}/config/pick-folder`, {
    method: "POST",
    headers: { Authorization: `Bearer ${token}` },
  });
  if (!r.ok) {
    let msg = `pick folder ${r.status}`;
    try {
      const j = (await r.json()) as { detail?: { error?: { message?: string } } | string };
      const d = j.detail;
      if (typeof d === "object" && d?.error?.message) msg = d.error.message;
    } catch {
      /* ignore */
    }
    throw new Error(msg);
  }
  const j = (await r.json()) as { path: string };
  return j.path;
}

function render(): void {
  const root = document.getElementById("app")!;
  root.replaceChildren(
    el(`
      <main style="font-family: system-ui, -apple-system, sans-serif; max-width: 44rem; margin: 0 auto; padding: 1rem;">
        <header style="margin-bottom: 1rem;">
          <h1 style="margin: 0 0 0.5rem 0;">MemoryAgent</h1>
          <p style="color: #555; margin: 0; font-size: 0.9rem;">Local-first assistant (M3). Paste your API token from the core log, then chat. Edit <strong>USER.md</strong> / <strong>SOUL.md</strong> mirrors below; saving reindexes search.</p>
        </header>
        <section style="background: #f8f8f8; padding: 0.75rem; border-radius: 8px; margin-bottom: 1rem;">
          <label style="font-size: 0.85rem; font-weight: 600;">Bearer token</label>
          <div style="display: flex; gap: 0.5rem; margin-top: 0.35rem; flex-wrap: wrap;">
            <input id="token" type="password" placeholder="Token" style="flex: 1; min-width: 12rem; padding: 0.5rem;" />
            <button id="saveTok" type="button">Save</button>
          </div>
        </section>
        <section id="welcome" style="display: none; background: #eef6ff; border: 1px solid #c8d9f0; border-radius: 8px; padding: 1rem; margin-bottom: 1rem;">
          <div id="welcomeBody" style="font-size: 0.95rem; line-height: 1.45;"></div>
          <button id="welcomeOk" type="button" style="margin-top: 0.75rem;">Got it</button>
        </section>
        <div id="thread" style="border: 1px solid #ddd; border-radius: 8px; min-height: 12rem; max-height: 22rem; overflow-y: auto; padding: 0.75rem; background: #fff;"></div>
        <p style="font-size: 0.8rem; color: #555; margin: 0.75rem 0 0.25rem 0;">Tip: start a message with <strong>Remember that …</strong> (or <strong>Note:</strong> / <strong>Save to memory:</strong>) to save it to long-term memory.</p>
        <div style="display: flex; gap: 0.5rem; margin-top: 0.75rem;">
          <input id="say" type="text" placeholder="Message…" style="flex: 1; padding: 0.6rem;" />
          <button id="send" type="button">Send</button>
        </div>
        <section style="margin-top: 1.25rem; padding-top: 1rem; border-top: 1px solid #eee;">
          <h2 style="font-size: 1rem; margin: 0 0 0.5rem 0;">Memory audit (Markdown mirror)</h2>
          <p style="font-size: 0.85rem; color: #555; margin: 0 0 0.5rem 0;">YAML front matter is preserved; <strong>only the Markdown body</strong> below the closing <code>---</code> is embedded for retrieval.</p>
          <div style="display: flex; gap: 0.5rem; flex-wrap: wrap; align-items: center; margin-bottom: 0.5rem;">
            <label style="font-size: 0.85rem;">File</label>
            <select id="mirrorPick" style="padding: 0.4rem;">
              <option value="user">USER.md — preferences &amp; facts</option>
              <option value="soul">SOUL.md — tone &amp; identity</option>
            </select>
            <button id="mirrorLoad" type="button">Load</button>
            <button id="mirrorSave" type="button">Save &amp; reindex</button>
          </div>
          <textarea id="mirrorBody" placeholder="Load a mirror file after setting your token…" style="width: 100%; min-height: 14rem; padding: 0.5rem; box-sizing: border-box; font-family: ui-monospace, monospace; font-size: 0.85rem;"></textarea>
          <p id="mirrorStat" style="font-size: 0.85rem; color: #333; margin-top: 0.5rem;"></p>
        </section>
        <section style="margin-top: 1.25rem; padding-top: 1rem; border-top: 1px solid #eee;">
          <h2 style="font-size: 1rem; margin: 0 0 0.5rem 0;">Folder access (watched roots)</h2>
          <p style="font-size: 0.85rem; color: #555; margin: 0 0 0.5rem 0;">
            Add folders you want MemoryAgent to watch/index. On macOS, you may need to grant Files &amp; Folders / Full Disk Access for your host app.
          </p>
          <div style="display:flex; gap:0.5rem; flex-wrap:wrap;">
            <input id="rootInput" type="text" placeholder="/absolute/path/to/folder" style="flex:1; min-width: 16rem; padding: 0.5rem;" />
            <button id="rootAdd" type="button">Add</button>
            <button id="rootPick" type="button">Pick Folder…</button>
            <button id="rootRefresh" type="button">Refresh</button>
            <button id="rootSave" type="button">Save</button>
          </div>
          <ul id="rootList" style="margin:0.6rem 0 0 1rem; padding:0;"></ul>
          <p id="rootStat" style="font-size: 0.85rem; color: #333; margin-top: 0.5rem;"></p>
        </section>
        <section style="margin-top: 1.25rem; padding-top: 1rem; border-top: 1px solid #eee;">
          <h2 style="font-size: 1rem; margin: 0 0 0.5rem 0;">Add memory</h2>
          <textarea id="memtext" placeholder="Text to remember…" style="width: 100%; min-height: 4rem; padding: 0.5rem; box-sizing: border-box;"></textarea>
          <button id="addmem" type="button" style="margin-top: 0.5rem;">Save to memory</button>
          <p id="memstat" style="font-size: 0.85rem; color: #333; margin-top: 0.5rem;"></p>
        </section>
        <section style="margin-top: 1rem; font-size: 0.8rem; color: #666;">
          <pre id="health" style="white-space: pre-wrap; margin: 0;">Loading health…</pre>
        </section>
      </main>
    `),
  );

  const thread = root.querySelector("#thread") as HTMLElement;
  const messages: Msg[] = [];

  function appendAssistant(html: string): void {
    const d = document.createElement("div");
    d.style.marginBottom = "0.75rem";
    d.style.padding = "0.5rem 0.65rem";
    d.style.background = "#f0f0f0";
    d.style.borderRadius = "6px";
    d.innerHTML = html;
    thread.appendChild(d);
    thread.scrollTop = thread.scrollHeight;
  }

  function appendUser(text: string): void {
    const d = document.createElement("div");
    d.style.marginBottom = "0.75rem";
    d.style.padding = "0.5rem 0.65rem";
    d.style.background = "#e3f2fd";
    d.style.borderRadius = "6px";
    d.textContent = text;
    thread.appendChild(d);
    thread.scrollTop = thread.scrollHeight;
  }

  function appendCitations(cits: NonNullable<Msg["citations"]>): void {
    if (!cits?.length) return;
    const box = document.createElement("div");
    box.style.fontSize = "0.8rem";
    box.style.color = "#444";
    box.style.marginBottom = "0.75rem";
    box.innerHTML =
      "<strong>Sources</strong><ul style='margin: 0.25rem 0 0 1rem;'>" +
      cits.map((c) => `<li><code>${escapeHtml(c.chunk_id.slice(0, 8))}…</code> — ${escapeHtml(c.snippet.slice(0, 120))}${c.snippet.length > 120 ? "…" : ""}</li>`).join("") +
      "</ul>";
    thread.appendChild(box);
    thread.scrollTop = thread.scrollHeight;
  }

  const welcomeEl = root.querySelector("#welcome") as HTMLElement;
  const welcomeBody = root.querySelector("#welcomeBody") as HTMLElement;
  if (shouldShowWelcome()) {
    welcomeEl.style.display = "block";
    welcomeBody.innerHTML =
      "<p>" + simpleMarkdown(WELCOME_INTRO) + "</p><p style='margin-top:0.75rem'>" + simpleMarkdown(WELCOME_DETAIL) + "</p>";
  }

  root.querySelector("#welcomeOk")!.addEventListener("click", () => {
    dismissWelcome();
    welcomeEl.style.display = "none";
  });

  const tokInput = root.querySelector("#token") as HTMLInputElement;
  tokInput.value = getToken();
  root.querySelector("#saveTok")!.addEventListener("click", () => {
    localStorage.setItem(TOKEN_KEY, tokInput.value.trim());
  });

  const say = root.querySelector("#say") as HTMLInputElement;
  const send = () => {
    const token = getToken() || tokInput.value.trim();
    if (!token) {
      alert("Set a bearer token first.");
      return;
    }
    localStorage.setItem(TOKEN_KEY, token);
    const text = say.value.trim();
    if (!text) return;
    if (shouldShowWelcome()) {
      dismissWelcome();
      welcomeEl.style.display = "none";
    }
    appendUser(text);
    messages.push({ role: "user", content: text });
    say.value = "";
    void (async () => {
      try {
        const { reply, citations } = await apiChat(messages, token);
        appendAssistant(simpleMarkdown(reply));
        appendCitations(citations ?? []);
        messages.push({ role: "assistant", content: reply, citations });
      } catch (e) {
        appendAssistant("<em>Error: " + String(e) + "</em>");
      }
    })();
  };
  root.querySelector("#send")!.addEventListener("click", send);
  say.addEventListener("keydown", (ev) => {
    if (ev.key === "Enter") send();
  });

  const mirrorBody = root.querySelector("#mirrorBody") as HTMLTextAreaElement;
  const mirrorStat = root.querySelector("#mirrorStat") as HTMLElement;
  const mirrorPick = root.querySelector("#mirrorPick") as HTMLSelectElement;
  const rootInput = root.querySelector("#rootInput") as HTMLInputElement;
  const rootList = root.querySelector("#rootList") as HTMLUListElement;
  const rootStat = root.querySelector("#rootStat") as HTMLElement;
  let watchedRoots: string[] = [];

  const renderRoots = () => {
    rootList.innerHTML = "";
    if (!watchedRoots.length) {
      const li = document.createElement("li");
      li.textContent = "(none)";
      li.style.color = "#666";
      rootList.appendChild(li);
      return;
    }
    for (const p of watchedRoots) {
      const li = document.createElement("li");
      li.style.marginBottom = "0.35rem";
      const code = document.createElement("code");
      code.textContent = p;
      code.style.marginRight = "0.5rem";
      const del = document.createElement("button");
      del.type = "button";
      del.textContent = "Remove";
      del.addEventListener("click", () => {
        watchedRoots = watchedRoots.filter((x) => x !== p);
        renderRoots();
      });
      li.appendChild(code);
      li.appendChild(del);
      rootList.appendChild(li);
    }
  };

  const loadRoots = async () => {
    const token = getToken() || tokInput.value.trim();
    if (!token) {
      rootStat.textContent = "Set a token first.";
      return;
    }
    rootStat.textContent = "Loading…";
    try {
      const cfg = await apiConfigGet(token);
      watchedRoots = Array.isArray(cfg.watched_roots) ? [...cfg.watched_roots] : [];
      renderRoots();
      rootStat.textContent = "Loaded watched roots.";
    } catch (e) {
      rootStat.textContent = String(e);
    }
  };

  const loadMirror = async () => {
    const token = getToken() || tokInput.value.trim();
    if (!token) {
      mirrorStat.textContent = "Set a token first.";
      return;
    }
    mirrorStat.textContent = "Loading…";
    try {
      const j = await apiMirrorGet(mirrorPick.value, token);
      mirrorBody.value = j.content;
      mirrorStat.textContent = "Loaded.";
    } catch (e) {
      mirrorStat.textContent = String(e);
    }
  };

  root.querySelector("#mirrorLoad")!.addEventListener("click", () => void loadMirror());
  root.querySelector("#mirrorSave")!.addEventListener("click", async () => {
    const token = getToken() || tokInput.value.trim();
    if (!token) {
      mirrorStat.textContent = "Set a token first.";
      return;
    }
    mirrorStat.textContent = "Saving…";
    try {
      await apiMirrorPut(mirrorPick.value, mirrorBody.value, token);
      mirrorStat.textContent = "Saved and reindexed.";
    } catch (e) {
      mirrorStat.textContent = String(e);
    }
  });
  mirrorPick.addEventListener("change", () => {
    mirrorBody.value = "";
    mirrorStat.textContent = "";
  });

  root.querySelector("#rootAdd")!.addEventListener("click", () => {
    const v = rootInput.value.trim();
    if (!v) {
      rootStat.textContent = "Enter a folder path.";
      return;
    }
    if (!watchedRoots.includes(v)) watchedRoots.push(v);
    rootInput.value = "";
    renderRoots();
    rootStat.textContent = "Added locally. Click Save to apply.";
  });
  root.querySelector("#rootPick")!.addEventListener("click", async () => {
    const token = getToken() || tokInput.value.trim();
    if (!token) {
      rootStat.textContent = "Set a token first.";
      return;
    }
    rootStat.textContent = "Opening folder picker…";
    try {
      const p = await apiPickFolder(token);
      if (!watchedRoots.includes(p)) watchedRoots.push(p);
      renderRoots();
      rootStat.textContent = "Picked folder. Click Save to apply.";
    } catch (e) {
      rootStat.textContent = String(e);
    }
  });
  root.querySelector("#rootRefresh")!.addEventListener("click", () => void loadRoots());
  root.querySelector("#rootSave")!.addEventListener("click", async () => {
    const token = getToken() || tokInput.value.trim();
    if (!token) {
      rootStat.textContent = "Set a token first.";
      return;
    }
    rootStat.textContent = "Saving…";
    try {
      const cfg = await apiConfigPatch(token, { watched_roots: watchedRoots });
      watchedRoots = Array.isArray(cfg.watched_roots) ? [...cfg.watched_roots] : watchedRoots;
      renderRoots();
      rootStat.textContent = "Saved. Watchers restarted.";
    } catch (e) {
      rootStat.textContent = String(e);
    }
  });

  root.querySelector("#addmem")!.addEventListener("click", async () => {
    const token = getToken() || tokInput.value.trim();
    const mem = (root.querySelector("#memtext") as HTMLTextAreaElement).value.trim();
    const stat = root.querySelector("#memstat")!;
    if (!token) {
      stat.textContent = "Set a token first.";
      return;
    }
    if (!mem) {
      stat.textContent = "Enter text.";
      return;
    }
    try {
      await apiMemory(mem, token);
      stat.textContent = "Saved.";
      (root.querySelector("#memtext") as HTMLTextAreaElement).value = "";
    } catch (e) {
      stat.textContent = String(e);
    }
  });

  fetch(`${API}/health`)
    .then((r) => r.json())
    .then((j) => {
      (root.querySelector("#health") as HTMLElement).textContent = JSON.stringify(j, null, 2);
    })
    .catch((e) => {
      (root.querySelector("#health") as HTMLElement).textContent = String(e);
    });

  // Best-effort initial load (shows "(none)" when unset or unauthenticated)
  renderRoots();
  void loadRoots();
}

function escapeHtml(s: string): string {
  return s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
}

render();
