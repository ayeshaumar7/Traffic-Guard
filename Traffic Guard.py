import ipaddress
import os
import threading
import time
import tkinter as tk
from collections import deque
from tkinter import filedialog, messagebox

try:
    import requests
except ImportError:
    requests = None

try:
    import winsound
    HAS_SOUND = True
except ImportError:
    HAS_SOUND = False


# ============================================================
# CONFIGURATION
# ============================================================
WINDOW_SIZE = 10        # seconds
MAX_REQUESTS = 5        # requests allowed per window
FONT = "Segoe UI"

# Ban rule: this many denials in a row = banned for this many seconds.
DENIALS_BEFORE_BAN = 3
BAN_SECONDS = 30

# --- Groq chatbot settings ---
GROQ_API_KEY = "API KEY HERE"
GROQ_MODEL = "API KEY MODEL HERE "
GROQ_URL = "API KEY URL HERE  "
SYSTEM_PROMPT = (
    "You are the Traffic Guard Project Assistant. "
    "You are an informational assistant for a Data Structures university "
    "project that demonstrates a rate limiter. "
    "\n\n"
    "Your ONLY purpose is to help the user understand the EXISTING Traffic "
    "Guard project and the concepts it demonstrates. "
    "\n\n"
    "You may explain: rate limiting, sliding window algorithms, queues, "
    "deques, dictionaries, sets, APIs, HTTP status codes, request limits, "
    "temporary bans, the traffic light, the audit log, the chatbot, and how "
    "the existing program behaves. "
    "\n\n"
    "You may explain existing code when the user asks what it does, but do "
    "NOT write, generate, modify, or rewrite code. "
    "\n\n"
    "Do NOT help the user build another rate limiter, recreate this project, "
    "add new features, design new functionality, improve the architecture, "
    "or create a similar project. Do NOT provide implementation steps, "
    "pseudocode, or coding instructions. "
    "\n\n"
    "Do NOT proactively suggest features or tell the user what they should "
    "add or change. Answer the question that was asked and stay focused on "
    "the existing project. "
    "\n\n"
    "If someone asks for code, implementation instructions, feature ideas, "
    "or help creating a similar project, politely say that you can explain "
    "the existing project's concepts and behavior, but cannot provide "
    "implementation help. "
    "\n\n"
    "Keep explanations clear, concise, and suitable for a university "
    "student explaining the project in a demonstration or viva."
)


client_queues = {}          # client IP -> deque of request timestamps
history = []                 # permanent audit history of every request
known_clients = set()        # unique client names
consecutive_denials = {}     # client IP -> denials in a row
banned_until = {}            # client IP -> unix time their ban ends

protection_enabled = True    # Attack mode (False) vs Protected mode (True)

THEMES = {
    "light": {
        "BG": "#f1f5f9", "CARD": "#ffffff", "TEXT": "#0f172a", "MUTED": "#64748b",
        "GREEN": "#16a34a", "ORANGE": "#d97706", "RED": "#dc2626", "BLUE": "#2563eb",
        "TRACK": "#e2e8f0", "ENTRY_BG": "#f8fafc", "DARK_DOT": "#1e293b",
    },
    "dark": {
        "BG": "#0f172a", "CARD": "#1e293b", "TEXT": "#e2e8f0", "MUTED": "#94a3b8",
        "GREEN": "#22c55e", "ORANGE": "#f59e0b", "RED": "#ef4444", "BLUE": "#38bdf8",
        "TRACK": "#334155", "ENTRY_BG": "#0f172a", "DARK_DOT": "#334155",
    },
}
theme_name = "light"
theme = THEMES[theme_name]


# ============================================================
# HELPERS
# ============================================================
def get_client_name():
    return client_entry.get().strip()


def get_client_ip():
    return ip_entry.get().strip()


def validate_ip(ip_address):
    try:
        ipaddress.ip_address(ip_address)
        return True
    except ValueError:
        return False


def get_or_create_client_queue(client_ip):
    if client_ip not in client_queues:
        client_queues[client_ip] = deque()
        known_clients.add(client_ip)
    return client_queues[client_ip]


def remove_expired_timestamps(request_queue, current_time):
    cutoff = current_time - WINDOW_SIZE
    while request_queue and request_queue[0] <= cutoff:
        request_queue.popleft()


def format_timestamp(timestamp):
    return time.strftime("%H:%M:%S", time.localtime(timestamp))


def format_report_timestamp(timestamp=None):
    return time.strftime("%d-%m-%Y %H:%M:%S", time.localtime(timestamp or time.time()))


def set_status(message, color):
    status_label.config(text=message, bg=color)


def usage_color(count):
    ratio = count / MAX_REQUESTS
    return theme["GREEN"] if ratio < 0.6 else theme["ORANGE"] if ratio < 1 else theme["RED"]


def is_banned(client_ip):
    return banned_until.get(client_ip, 0) > time.time()


def read_inputs():
    """Return (name, ip) if both are valid, otherwise show a warning and return None."""
    name, ip = get_client_name(), get_client_ip()
    if not name:
        messagebox.showwarning("Name needed", "Please type a client name first.")
        client_entry.focus_set()
    elif not ip:
        messagebox.showwarning("IP address needed", "Please enter the client's IP address.")
        ip_entry.focus_set()
    elif not validate_ip(ip):
        messagebox.showerror(
            "Invalid IP address",
            "Please enter a valid IPv4 or IPv6 address.\n\nExample:\n192.168.1.25")
        ip_entry.focus_set()
    else:
        return name, ip
    return None


def play_sound(kind):
    """Play a short alert beep in the background. Does nothing on non-Windows systems."""
    if not HAS_SOUND:
        return

    def worker():
        try:
            if kind == "deny":
                winsound.Beep(650, 150)
            elif kind == "ban":
                winsound.Beep(400, 350)
        except RuntimeError:
            pass

    threading.Thread(target=worker, daemon=True).start()


# ============================================================
# DRAWING
# ============================================================
def draw_traffic_light(active_color):
    light.delete("all")
    light.create_rectangle(4, 2, 46, 98, fill=theme["DARK_DOT"], outline=theme["MUTED"], width=2)
    for y, color in ((18, theme["RED"]), (50, theme["ORANGE"]), (82, theme["GREEN"])):
        light.create_oval(13, y - 12, 37, y + 12,
                          fill=color if color == active_color else theme["TRACK"], outline="")


def draw_theme_toggle(canvas, is_dark):
    """Draw a small pill-shaped on/off switch reflecting the current theme."""
    canvas.delete("all")
    w, h = 54, 26
    r = h / 2
    fill = theme["BLUE"] if is_dark else theme["TRACK"]

    # Rounded track: two end-caps + a rectangle to bridge them.
    canvas.create_oval(0, 0, h, h, fill=fill, outline="")
    canvas.create_oval(w - h, 0, w, h, fill=fill, outline="")
    canvas.create_rectangle(r, 0, w - r, h, fill=fill, outline="")

    # Knob slides to the right when dark mode is on.
    knob_cx = (w - r) if is_dark else r
    canvas.create_oval(knob_cx - r + 3, 3, knob_cx + r - 3, h - 3, fill="white", outline="")


def draw_timeline(request_queue):
    timeline.delete("all")
    left, right, y = 50, max(timeline.winfo_width(), 400) - 50, 32
    timeline.create_line(left, y, right, y, fill=theme["TRACK"], width=4)
    for x, label in ((left, f"{WINDOW_SIZE} sec ago"),
                     ((left + right) / 2, f"{WINDOW_SIZE // 2} sec ago"),
                     (right, "now")):
        timeline.create_text(x, y + 22, text=label, fill=theme["MUTED"])

    now = time.time()
    for timestamp in request_queue:
        age = now - timestamp
        x = right - (age / WINDOW_SIZE) * (right - left)
        color = theme["ORANGE"] if age > WINDOW_SIZE * 0.8 else theme["BLUE"]
        timeline.create_oval(x - 9, y - 9, x + 9, y + 9, fill=color, outline="")


def draw_slots(count):
    slots.delete("all")
    gap = 8
    box = (max(slots.winfo_width(), 250) - gap * (MAX_REQUESTS - 1)) / MAX_REQUESTS
    color = usage_color(count)
    for i in range(MAX_REQUESTS):
        x, used = i * (box + gap), i < count
        slots.create_rectangle(x, 0, x + box, 34,
                               fill=color if used else theme["TRACK"], outline="")
        slots.create_text(x + box / 2, 17, text="\U0001F4E8" if used else str(i + 1),
                          fill="white" if used else theme["MUTED"], font=(FONT, 12, "bold"))


# ============================================================
# SUMMARY
# ============================================================
def update_summary():
    total = len(history)
    allowed = sum(1 for r in history if r["allowed"])
    denied = total - allowed
    rate = denied / total * 100 if total else 0

    total_value.config(text=str(total))
    allowed_value.config(text=str(allowed))
    denied_value.config(text=str(denied))
    people_value.config(text=str(len(known_clients)))

    summary_text.config(
        text=(f"So far: {total} requests sent. {allowed} accepted, "
              f"{denied} blocked ({rate:.0f}% blocked).")
        if total else "Nothing yet. Press Send Request to get started!")

    per_client = {}  # ip -> [allowed, denied]
    for r in history:
        per_client.setdefault(r["ip"], [0, 0])[0 if r["allowed"] else 1] += 1

    parts = [f"{ip}  OK:{per_client[ip][0]}  BLOCKED:{per_client[ip][1]}"
             for ip in sorted(per_client)[:5]]
    if len(per_client) > 5:
        parts.append(f"+{len(per_client) - 5} more")
    people_label.config(text="      ".join(parts) if parts else "No people yet")


# ============================================================
# ACTIVE WINDOW
# ============================================================
def update_active_window():
    client_ip = get_client_ip()
    request_queue = client_queues.get(client_ip)
    now = time.time()
    if request_queue is not None:
        remove_expired_timestamps(request_queue, now)
    count = len(request_queue) if request_queue else 0

    recent_text.config(state="normal")
    recent_text.delete("1.0", tk.END)
    if not request_queue:
        recent_text.insert(tk.END, "Nothing yet. Press Send Request!")
    else:
        for pos, ts in enumerate(request_queue, start=1):
            recent_text.insert(
                tk.END, f"{pos}. sent at {format_timestamp(ts)}  ({int(now - ts)}s ago)\n")
    recent_text.config(state="disabled")

    used_label.config(
        text=f"Requests used: {count} of {MAX_REQUESTS}   ({MAX_REQUESTS - count} left)")

    if not protection_enabled:
        retry_label.config(text="Protection is OFF - nothing is being blocked", fg=theme["ORANGE"])
    elif is_banned(client_ip):
        wait = banned_until[client_ip] - now
        retry_label.config(text=f"Banned - {wait:.0f}s left", fg=theme["RED"])
    elif count >= MAX_REQUESTS:
        wait = request_queue[0] + WINDOW_SIZE - now
        retry_label.config(text=f"Please wait {wait:.1f} seconds, then try again", fg=theme["RED"])
    else:
        retry_label.config(text="You can send a request now", fg=theme["GREEN"])

    draw_timeline(request_queue or [])
    draw_slots(count)
    draw_traffic_light(usage_color(count))


# ============================================================
# AUDIT LOG
# ============================================================
def update_audit_log():
    audit_text.config(state="normal")
    audit_text.delete("1.0", tk.END)
    if not history:
        audit_text.insert(tk.END, "No requests have been recorded yet.")
    else:
        for n, r in enumerate(history, start=1):
            audit_text.insert(
                tk.END,
                f"{n:03d} | {format_timestamp(r['time'])} | {r['client']:<12} | "
                f"{r['ip']:<15} | {r['status']}\n",
                "allowed" if r["allowed"] else "denied")
        audit_text.see(tk.END)
    audit_text.config(state="disabled")
    audit_count_label.config(text=f"Audit records: {len(history)}")


# ============================================================
# REQUEST PROCESSING
# ============================================================
def process_request(client_name, client_ip):
    """
    Runs one request through the sliding window + ban rules.
    Returns (allowed: bool, message: str).
    Used by Send Request, Spam Test, and the chatbot.
    """
    now = time.time()

    if not protection_enabled:
        history.append({"client": client_name, "ip": client_ip, "time": now,
                        "status": "ALLOWED (protection off)", "allowed": True})
        known_clients.add(client_ip)
        msg = "Allowed - protection is OFF"
        set_status(msg, theme["ORANGE"])
        return True, msg

    if is_banned(client_ip):
        wait = banned_until[client_ip] - now
        msg = f"Banned for {wait:.0f}s (too many attempts)"
        set_status(msg, theme["RED"])
        play_sound("ban")
        return False, msg

    request_queue = get_or_create_client_queue(client_ip)
    remove_expired_timestamps(request_queue, now)

    allowed = len(request_queue) < MAX_REQUESTS
    if allowed:
        request_queue.append(now)
        consecutive_denials[client_ip] = 0
        status, msg = "ALLOWED (200)", "Request accepted!"
    else:
        status = "DENIED (429 Too Many Requests)"
        consecutive_denials[client_ip] = consecutive_denials.get(client_ip, 0) + 1
        msg = "Too many requests! Please wait a moment."
        play_sound("deny")

        if consecutive_denials[client_ip] >= DENIALS_BEFORE_BAN:
            banned_until[client_ip] = now + BAN_SECONDS
            consecutive_denials[client_ip] = 0
            msg = f"Banned for {BAN_SECONDS}s (too many attempts)"
            play_sound("ban")

    history.append({"client": client_name, "ip": client_ip, "time": now,
                    "status": status, "allowed": allowed})
    set_status(msg, theme["GREEN"] if allowed else theme["RED"])
    return allowed, msg


def refresh_all():
    update_active_window()
    update_audit_log()
    update_summary()


def send_request():
    inputs = read_inputs()
    if inputs:
        process_request(*inputs)
        refresh_all()


def send_burst():
    """Send many requests quickly to trigger 429."""
    inputs = read_inputs()
    if inputs:
        for _ in range(MAX_REQUESTS + 3):
            process_request(*inputs)
        refresh_all()


def reset_client():
    ip = get_client_ip()
    if ip in client_queues:
        client_queues[ip].clear()
    consecutive_denials[ip] = 0
    banned_until.pop(ip, None)
    set_status("This person was reset", theme["MUTED"])
    refresh_all()


def reset_system():
    client_queues.clear()
    history.clear()
    known_clients.clear()
    consecutive_denials.clear()
    banned_until.clear()
    set_status("Everything was cleared", theme["MUTED"])
    refresh_all()


def toggle_protection():
    global protection_enabled
    protection_enabled = not protection_enabled
    if protection_enabled:
        protection_button.config(text="Protection: ON", bg=theme["GREEN"])
        set_status("Protection turned ON", theme["GREEN"])
    else:
        protection_button.config(text="Protection: OFF", bg=theme["RED"])
        set_status("Protection turned OFF - attack mode", theme["RED"])
    refresh_all()


# ============================================================
# TEXT REPORT
# ============================================================
def generate_report():
    """Save a human-readable TXT report of configuration, stats and history."""
    if not history:
        messagebox.showinfo("Nothing to report", "No requests have been recorded yet.")
        return

    path = filedialog.asksaveasfilename(
        title="Generate Traffic Guard Report",
        defaultextension=".txt",
        filetypes=[("Text Report", "*.txt"), ("All files", "*.*")],
        initialfile="traffic_guard_report.txt")
    if not path:
        return

    total = len(history)
    allowed = sum(1 for r in history if r["allowed"])
    denied = total - allowed

    stats = {}
    for r in history:
        s = stats.setdefault(r["client"], {"ip": r["ip"], "allowed": 0, "denied": 0, "total": 0})
        s["total"] += 1
        s["ip"] = r["ip"]
        s["allowed" if r["allowed"] else "denied"] += 1

    sep, line = "=" * 70, "-" * 70
    out = [sep, "                    TRAFFIC GUARD REPORT", sep, "",
           f"Report Generated : {format_report_timestamp()}",
           "Application       : Traffic Guard - Rate Limiter", "",
           "RATE LIMIT CONFIGURATION", line,
           f"Maximum Requests : {MAX_REQUESTS}",
           f"Time Window      : {WINDOW_SIZE} seconds", "",
           "SUMMARY", line,
           f"Total Requests   : {total}",
           f"Accepted         : {allowed}",
           f"Blocked          : {denied}",
           f"Blocked Rate     : {denied / total * 100:.1f}%",
           f"Unique Clients   : {len(known_clients)}", "",
           "CLIENT SUMMARY", line]

    for client in sorted(stats):
        d = stats[client]
        out += [f"Client       : {client}", f"IP Address   : {d['ip']}",
                f"Requests     : {d['total']}", f"Accepted     : {d['allowed']}",
                f"Blocked      : {d['denied']}", ""]

    out += ["REQUEST HISTORY", line]
    for n, r in enumerate(history, start=1):
        out += [f"{n:03d} | Client: {r['client']}",
                f"    | IP Address: {r['ip']}",
                f"    | Time: {format_report_timestamp(r['time'])}",
                f"    | Status: {r['status']}",
                f"    | Allowed: {'YES' if r['allowed'] else 'NO'}", ""]

    out += [sep, "                    END OF REPORT", sep]

    try:
        with open(path, "w", encoding="utf-8") as file:
            file.write("\n".join(out))
        messagebox.showinfo(
            "Report Generated",
            f"Professional report saved successfully.\n\n"
            f"Records included: {total}\n\nFile:\n{path}")
    except OSError as error:
        messagebox.showerror("Report Error", f"Could not save the report.\n\n{error}")


def refresh_display():
    """Refresh often so dots drift smoothly and expire without new requests."""
    update_active_window()
    root.after(150, refresh_display)


# ------------------------------ Chatbot ------------------------------ #
def call_groq(user_message):
    """Runs in a background thread. Returns the reply text or an error message."""
    if requests is None:
        return "The 'requests' library isn't installed. Run: pip install requests"
    if not GROQ_API_KEY:
        return "No API key found. Set the GROQ_API_KEY environment variable."
    try:
        response = requests.post(
            GROQ_URL,
            headers={"Authorization": f"Bearer {GROQ_API_KEY}"},
            json={"model": GROQ_MODEL,
                  "messages": [{"role": "system", "content": SYSTEM_PROMPT},
                              {"role": "user", "content": user_message}]},
            timeout=15)
        data = response.json()
        if response.status_code != 200:
            return f"API error: {data.get('error', {}).get('message', response.text)}"
        return data["choices"][0]["message"]["content"]
    except Exception as error:
        return f"Could not reach the chatbot: {error}"


def show_chat_reply(text):
    chat_reply.config(state="normal")
    chat_reply.delete("1.0", tk.END)
    chat_reply.insert(tk.END, text)
    chat_reply.config(state="disabled")


def ask_chatbot():
    inputs = read_inputs()
    if not inputs:
        return

    client_name, client_ip = inputs

    question = chat_entry.get().strip()
    if not question:
        messagebox.showwarning("Question needed", "Type a question for the chatbot first.")
        return

    # Clear the question box after sending.
    chat_entry.delete(0, tk.END)

    # Chatbot is separate from the rate limiter.
    # Do NOT call process_request() here.

    show_chat_reply("Thinking...")
    ask_button.config(state="disabled")

    def worker():
        reply = call_groq(question)
        root.after(0, lambda: (
            show_chat_reply(reply),
            ask_button.config(state="normal")
        ))

    threading.Thread(target=worker, daemon=True).start()
# ============================================================
# THEME TOGGLE
# ============================================================
def toggle_theme():
    global theme_name, theme
    theme_name = "dark" if theme_name == "light" else "light"
    theme = THEMES[theme_name]
    for widget in root.winfo_children():
        widget.destroy()
    build_ui()
    refresh_all()


# ============================================================
# GUI HELPERS
# ============================================================
def make_card(parent, title):
    card = tk.Frame(parent, bg=theme["CARD"], padx=14, pady=12)
    tk.Label(card, text=title, bg=theme["CARD"], fg=theme["TEXT"],
             font=(FONT, 11, "bold")).pack(anchor="w", pady=(0, 8))
    return card


def lighten(color):
    r, g, b = (int(color[i:i + 2], 16) for i in (1, 3, 5))
    return "#%02x%02x%02x" % (min(r + 25, 255), min(g + 25, 255), min(b + 25, 255))


def make_button(parent, text, command, color):
    button = tk.Button(parent, text=text, command=command, bg=color, fg="white",
                       activebackground=lighten(color), activeforeground="white",
                       font=(FONT, 11, "bold"), relief="flat", bd=0, pady=10,
                       cursor="hand2")
    button.bind("<Enter>", lambda e: button.config(bg=lighten(color)))
    button.bind("<Leave>", lambda e: button.config(bg=color))
    return button


def make_tile(parent, column, title, color):
    tile = tk.Frame(parent, bg=theme["CARD"], padx=10, pady=8)
    tile.grid(row=0, column=column, padx=4, sticky="ew")
    parent.columnconfigure(column, weight=1)
    value = tk.Label(tile, text="0", bg=theme["CARD"], fg=color, font=(FONT, 22, "bold"))
    value.pack()
    tk.Label(tile, text=title, bg=theme["CARD"], fg=theme["MUTED"], font=(FONT, 9)).pack()
    return value


def make_entry(parent, width, default):
    entry = tk.Entry(parent, width=width, font=(FONT, 12), relief="flat",
                     bg=theme["ENTRY_BG"], fg=theme["TEXT"], insertbackground=theme["TEXT"])
    entry.insert(0, default)
    return entry


# ============================================================
# BUILD UI  (called once at start, and again when theme toggles)
# ============================================================
def build_ui():
    global light, client_entry, ip_entry, status_label, retry_label
    global used_label, slots, recent_text, timeline
    global audit_count_label, audit_text
    global total_value, allowed_value, denied_value, people_value
    global summary_text, people_label, protection_button
    global chat_entry, chat_reply, ask_button

    root.configure(bg=theme["BG"])

    # ---------------- Scrollable container ----------------
    canvas = tk.Canvas(root, bg=theme["BG"], highlightthickness=0)
    scrollbar = tk.Scrollbar(root, orient="vertical", command=canvas.yview)
    scrollable_frame = tk.Frame(canvas, bg=theme["BG"])

    scrollable_frame.bind(
        "<Configure>",
        lambda e: canvas.configure(scrollregion=canvas.bbox("all"))
    )

    canvas_window = canvas.create_window(
        (0, 0),
        window=scrollable_frame,
        anchor="nw"
    )

    def resize_scrollable_frame(event):
        canvas.itemconfig(canvas_window, width=event.width)

    canvas.bind("<Configure>", resize_scrollable_frame)
    canvas.configure(yscrollcommand=scrollbar.set)

    scrollbar.pack(side="right", fill="y")
    canvas.pack(side="left", fill="both", expand=True)

    def on_mousewheel(event):
        canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")

    canvas.bind_all("<MouseWheel>", on_mousewheel)

    # Make all existing UI use the scrollable frame instead of root.
    root_ui = scrollable_frame

    root_ui.columnconfigure(0, weight=1)

    # ---------------- Header ----------------
    header = tk.Frame(root_ui, bg=theme["BG"], padx=20, pady=6)
    header.grid(row=0, column=0, sticky="ew")

    top_right = tk.Frame(header, bg=theme["BG"])
    top_right.pack(side="right")
    light = tk.Canvas(top_right, width=50, height=100, bg=theme["BG"], highlightthickness=0)
    light.pack()

    # Theme toggle: a small pill switch + label, sitting neatly under the traffic light.
    is_dark = theme_name == "dark"
    toggle_row = tk.Frame(top_right, bg=theme["BG"], cursor="hand2")
    toggle_row.pack(pady=(10, 0))

    toggle_label = tk.Label(
        toggle_row,
        text="Dark mode" if is_dark else "Light mode",
        bg=theme["BG"], fg=theme["MUTED"], font=(FONT, 9, "bold"), cursor="hand2")
    toggle_label.pack(side="left", padx=(0, 6))

    theme_switch = tk.Canvas(toggle_row, width=54, height=26, bg=theme["BG"],
                             highlightthickness=0, cursor="hand2")
    theme_switch.pack(side="left")
    draw_theme_toggle(theme_switch, is_dark)

    theme_switch.bind("<Button-1>", lambda e: toggle_theme())
    toggle_label.bind("<Button-1>", lambda e: toggle_theme())
    toggle_row.bind("<Button-1>", lambda e: toggle_theme())

    title_frame = tk.Frame(header, bg=theme["BG"])
    title_frame.pack(side="left")
    tk.Label(title_frame, text="Traffic Guard", bg=theme["BG"], fg=theme["TEXT"],
             font=(FONT, 24, "bold")).pack(anchor="w")
    tk.Label(title_frame, bg=theme["BG"], fg=theme["MUTED"], font=(FONT, 11), justify="left",
             text=(f"Everyone can send {MAX_REQUESTS} requests every {WINDOW_SIZE} seconds.\n"
                   f"Send too many and you get blocked for a little while.")
             ).pack(anchor="w", pady=(2, 6))
    tk.Label(title_frame, bg=theme["BG"], fg=theme["BLUE"], font=(FONT, 10, "bold"),
             text=("Step 1: Enter client details      "
                   "Step 2: Send Request      "
                   "Step 3: Watch the traffic light")).pack(anchor="w")

    # ---------------- Controls ----------------
    controls = make_card(root_ui, "Controls")
    controls.grid(row=1, column=0, padx=20, pady=(0, 10), sticky="ew")

    row = tk.Frame(controls, bg=theme["CARD"])
    row.pack(fill="x")

    tk.Label(row, text="Name:", bg=theme["CARD"], fg=theme["TEXT"], font=(FONT, 11)).pack(side="left")
    client_entry = make_entry(row, 12, "Alice")
    client_entry.pack(side="left", padx=(6, 12), ipady=6)

    tk.Label(row, text="IP:", bg=theme["CARD"], fg=theme["TEXT"], font=(FONT, 11)).pack(side="left")
    ip_entry = make_entry(row, 13, "192.168.1.25")
    ip_entry.pack(side="left", padx=(6, 14), ipady=6)

    client_entry.bind("<KeyRelease>", lambda e: update_active_window())
    ip_entry.bind("<KeyRelease>", lambda e: update_active_window())

    for label, command, color in (
            ("Send Request", send_request, theme["BLUE"]),
            ("Spam Test", send_burst, theme["ORANGE"]),
            ("Reset Person", reset_client, theme["MUTED"]),
            ("Clear All", reset_system, theme["RED"]),
            ("Generate Report", generate_report, "#7c3aed")):
        make_button(row, label, command, color).pack(side="left", padx=4, fill="x", expand=True)

    protection_row = tk.Frame(controls, bg=theme["CARD"])
    protection_row.pack(fill="x", pady=(8, 0))
    protection_button = make_button(
        protection_row,
        "Protection: ON" if protection_enabled else "Protection: OFF",
        toggle_protection,
        theme["GREEN"] if protection_enabled else theme["RED"])
    protection_button.pack(fill="x")

    # ---------------- Timeline ----------------
    timeline_card = make_card(
        root_ui, "Live Activity: last 10 seconds (each dot disappears after 10 seconds)")
    timeline_card.grid(row=2, column=0, padx=20, pady=(0, 10), sticky="ew")
    timeline = tk.Canvas(timeline_card, height=55, bg=theme["CARD"], highlightthickness=0)
    timeline.pack(fill="x")

    # ---------------- Bottom content ----------------
    content = tk.Frame(root_ui, bg=theme["BG"])
    content.grid(row=3, column=0, padx=20, pady=(0, 20), sticky="ew")
    content.columnconfigure(0, weight=1)
    content.columnconfigure(1, weight=1)

    # Left column
    left = tk.Frame(content, bg=theme["BG"])
    left.grid(row=0, column=0, padx=(0, 10), sticky="nsew")
    left.columnconfigure(0, weight=1)

    status_card = make_card(left, "Latest Result")
    status_card.grid(row=0, column=0, pady=(0, 10), sticky="ew")
    status_label = tk.Label(status_card, text="Ready! Send your first request.",
                            bg=theme["MUTED"], fg="white", font=(FONT, 15, "bold"),
                            pady=12, wraplength=300)
    status_label.pack(fill="x")
    retry_label = tk.Label(status_card, text="You can send a request now",
                           bg=theme["CARD"], fg=theme["GREEN"], font=(FONT, 11, "bold"))
    retry_label.pack(pady=(8, 0))

    tickets_card = make_card(left, "Requests Used")
    tickets_card.grid(row=1, column=0, pady=(0, 10), sticky="ew")
    used_label = tk.Label(tickets_card, text="", bg=theme["CARD"], fg=theme["TEXT"], font=(FONT, 10))
    used_label.pack(anchor="w")
    slots = tk.Canvas(tickets_card, height=34, bg=theme["CARD"], highlightthickness=0)
    slots.pack(fill="x", pady=(6, 8))
    recent_text = tk.Text(tickets_card, height=3, wrap="none", font=(FONT, 10),
                          bg=theme["ENTRY_BG"], fg=theme["TEXT"], relief="flat", bd=0, padx=8, pady=6)
    recent_text.pack(fill="both")
    recent_text.config(state="disabled")

    chat_card = make_card(left, "Ask About the Project")
    chat_card.grid(row=2, column=0, sticky="ew")
    chat_row = tk.Frame(chat_card, bg=theme["CARD"])
    chat_row.pack(fill="x")
    chat_entry = tk.Entry(chat_row, font=(FONT, 11), relief="flat", bg=theme["ENTRY_BG"],
                          fg=theme["TEXT"], insertbackground=theme["TEXT"])
    chat_entry.pack(side="left", fill="x", expand=True, ipady=6)
    chat_entry.bind("<Return>", lambda e: (ask_chatbot(), "break")[1])
    ask_button = make_button(chat_row, "Ask", ask_chatbot, theme["BLUE"])
    ask_button.pack(side="left", padx=(6, 0))
    chat_reply_frame = tk.Frame(chat_card, bg=theme["CARD"])
    chat_reply_frame.pack(fill="both", expand=True, pady=(8, 0))
    chat_reply_scrollbar = tk.Scrollbar(chat_reply_frame)
    chat_reply_scrollbar.pack(side="right", fill="y")
    chat_reply = tk.Text(chat_reply_frame, height=10, wrap="word", font=(FONT, 10),
                     bg=theme["ENTRY_BG"], fg=theme["TEXT"], relief="flat", bd=0, padx=8, pady=6,
                     yscrollcommand=chat_reply_scrollbar.set)
    chat_reply.pack(side="left", fill="both", expand=True)
    chat_reply_scrollbar.config(command=chat_reply.yview)
    chat_reply.insert(tk.END, "Ask a question about rate limiters, queues, or this project!")
    chat_reply.config(state="disabled")

    # Right column
    right = tk.Frame(content, bg=theme["BG"])
    right.grid(row=0, column=1, sticky="nsew")
    right.columnconfigure(0, weight=1)

    audit_card = make_card(right, "Audit Log (everything that happened)")
    audit_card.grid(row=0, column=0, pady=(0, 10), sticky="nsew")
    audit_count_label = tk.Label(audit_card, text="Audit records: 0",
                                 bg=theme["CARD"], fg=theme["TEXT"], font=(FONT, 10))
    audit_count_label.pack(anchor="w", pady=(0, 6))

    log_frame = tk.Frame(audit_card, bg=theme["CARD"])
    log_frame.pack(fill="both", expand=True)
    scrollbar = tk.Scrollbar(log_frame)
    scrollbar.pack(side="right", fill="y")
    audit_text = tk.Text(log_frame, height=6, wrap="none", font=("Consolas", 10),
                         bg=theme["ENTRY_BG"], fg=theme["TEXT"], relief="flat", bd=0, padx=8, pady=6,
                         yscrollcommand=scrollbar.set)
    audit_text.pack(side="left", fill="both", expand=True)
    scrollbar.config(command=audit_text.yview)
    audit_text.tag_config("allowed", foreground=theme["GREEN"])
    audit_text.tag_config("denied", foreground=theme["RED"])
    audit_text.config(state="disabled")

    # Summary
    summary_card = make_card(right, "Summary")
    summary_card.grid(row=1, column=0, sticky="ew")
    tiles = tk.Frame(summary_card, bg=theme["CARD"])
    tiles.pack(fill="x")
    total_value = make_tile(tiles, 0, "Total requests", theme["BLUE"])
    allowed_value = make_tile(tiles, 1, "Accepted", theme["GREEN"])
    denied_value = make_tile(tiles, 2, "Blocked", theme["RED"])
    people_value = make_tile(tiles, 3, "People", theme["ORANGE"])

    summary_text = tk.Label(summary_card, bg=theme["CARD"], fg=theme["TEXT"], font=(FONT, 10),
                            anchor="w", justify="left", wraplength=650)
    summary_text.pack(anchor="w", pady=(10, 4))
    people_label = tk.Label(summary_card, bg=theme["CARD"], fg=theme["MUTED"], font=(FONT, 10),
                            anchor="w", justify="left", wraplength=650)
    people_label.pack(anchor="w")

    client_entry.focus_set()


# ============================================================
# START
# ============================================================
root = tk.Tk()
root.title("Traffic Guard - Rate Limiter")
root.geometry("1200x900")
root.minsize(1050, 850)

build_ui()
refresh_all()

root.after(150, refresh_display)
root.bind("<Return>", lambda event: send_request())
root.mainloop()