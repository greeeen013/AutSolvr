import os
import sys
import threading
import requests
import pyautogui
from PIL import Image
import pystray
from io import BytesIO
import tkinter as tk
import time
import pyperclip
import ctypes

# Hide console window immediately
def hide_console():
    if os.name == 'nt':
        ctypes.windll.user32.ShowWindow(ctypes.windll.kernel32.GetConsoleWindow(), 0)

# Configuration
SERVER_URL = "http://127.0.0.1:5000/solve"
# SERVER_URL = "https://test.420013.xyz/solve"
ICON_PATH = "icon.png"

# Global state for debug window
debug_window = None

def log(message):
    """Logs message to debug window if open, otherwise print (which is hidden in .pyw)."""
    # print(message) # Optional: print to stdout if checking logs later
    if debug_window:
        debug_window.log(message)

def capture_and_solve(icon):
    """Captures screenshot, sends to server, and clicks coordinates."""
    log("Capturing screenshot...")
    try:
        # Press ESC to close any open menu (e.g. system tray/game menu)
        pyautogui.press('esc')
        time.sleep(0.2) 

        # 1. Capture Screen
        screenshot = pyautogui.screenshot()
        
        # 2. Prepare file for upload
        img_byte_arr = BytesIO()
        screenshot.save(img_byte_arr, format='PNG')
        img_byte_arr.seek(0)
        
        # 3. Send to Server
        log(f"Sending to {SERVER_URL}...")
        files = {'image': ('screenshot.png', img_byte_arr, 'image/png')}
        response = requests.post(SERVER_URL, files=files)
        
        if response.status_code == 200:
            coords_list = response.json()
            log(f"Received coordinates: {len(coords_list)} items")
            
            if not coords_list:
                log("No answers found.")
                return

            # Collect answer texts for clipboard
            answer_texts = []
            
            for point in coords_list:
                x, y = point['x'], point['y']
                text = point.get('text', '')
                if text:
                    answer_texts.append(text)
                
                log(f"Clicking at ({x}, {y})")
                pyautogui.click(x, y)
                
            # Copy answers to clipboard
            if answer_texts:
                full_text = "; ".join(answer_texts)
                pyperclip.copy(full_text)
                log(f"Copied to clipboard: {full_text[:30]}...")
                
        else:
            log(f"Server error: {response.status_code} - {response.text}")

    except Exception as e:
        log(f"Error: {e}")

def on_tray_click(icon, item):
    """Handler for clicking the tray icon (default action)."""
    # Simply trigger the solve process
    # Run in thread to not block the tray icon
    threading.Thread(target=capture_and_solve, args=(icon,)).start()

def open_debug_window(icon, item):
    """Opens a hidden console/debug window."""
    global debug_window
    if debug_window is None:
        root = tk.Tk()
        debug_window = DebugWindow(root)
        root.mainloop()
        debug_window = None

def exit_app(icon, item):
    """Stops the application."""
    icon.stop()
    sys.exit()

class DebugWindow:
    def __init__(self, master):
        self.master = master
        master.title("MicrosoftEdge Debug")
        master.geometry("400x300")
        
        self.text_area = tk.Text(master)
        self.text_area.pack(expand=True, fill='both')
        
    def log(self, text):
        self.text_area.insert(tk.END, text + "\n")
        self.text_area.see(tk.END)

def clear_action(icon, item):
    """Simulates 'Open' action: Presses ESC and clears clipboard."""
    pyautogui.press('esc')
    try:
        pyperclip.copy("")
    except:
        pyperclip.copy(" ")

def setup_tray():
    # Hide console if running normally
    hide_console()

    if not os.path.exists(ICON_PATH):
        print(f"Error: Icon not found at {ICON_PATH}")
        return

    image = Image.open(ICON_PATH)
    
    icon = pystray.Icon("MicrosoftEdge", image, "MicrosoftEdge")

    icon.menu = pystray.Menu(
        # Result: The 'Solve' item is default (triggered by tray click) but hidden from menu
        pystray.MenuItem("Solve", on_tray_click, default=True, visible=False),
        pystray.MenuItem("Open", clear_action),
        pystray.MenuItem("Exit", exit_app)
    )

    icon.run()

if __name__ == '__main__':
    setup_tray()
