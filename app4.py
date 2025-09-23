from openai import OpenAI
from dotenv import load_dotenv
load_dotenv()

from playwright.sync_api import sync_playwright
import base64
import time
from PIL import Image
from io import BytesIO

# -----------------------------
# Messages (add a system rule to avoid confirmation prompts)
# -----------------------------
input_messages = [
    {
        "role": "system",
        "content": (
            "You are controlling a browser with the Computer Use tool. "
            "When a contact form is fully filled, SUBMIT IT without asking for confirmation. "
            "If you believe a confirmation is required, assume the answer is YES and proceed."
        )
    },
    {
        "role": "user",
        "content": (
            "Open riis.com, go to the contact us page and enter Godfrey Nolan, "
            "godfrey@riis.com and enter the message hello from the openai meetup. "
            "Click on the submit button when the form is complete."
        )
    }
]

# -----------------------------
# Tools
# -----------------------------
tools = [{
    "type": "computer_use_preview",
    "display_width": 1024,
    "display_height": 768,
    "environment": "browser",
}]

# -----------------------------
# OpenAI client
# -----------------------------
client = OpenAI()

# -----------------------------
# Helpers
# -----------------------------
def show_image(base_64_image):
    image_data = base64.b64decode(base_64_image)
    image = Image.open(BytesIO(image_data))
    image.show()

def get_screenshot(page):
    """Take a screenshot using Playwright and return the image bytes."""
    return page.screenshot()

def handle_model_action(browser, page, action):
    """Executes a single computer action produced by the model."""
    action_type = action.type

    try:
        # If a new page/tab was opened, switch to it
        all_pages = browser.contexts[0].pages
        if len(all_pages) > 1 and all_pages[-1] != page:
            page = all_pages[-1]
            print("Switched to new page/tab")

        match action_type:
            case "click":
                x, y = action.x, action.y
                button = action.button
                print(f"Clicking at ({x}, {y}) with button {button}")
                page.mouse.click(x, y, button=button)

            case "scroll":
                x, y = action.x, action.y
                scroll_x, scroll_y = action.scroll_x, action.scroll_y
                print(f"Scroll at ({x}, {y}) by (x={scroll_x}, y={scroll_y})")
                page.mouse.move(x, y)
                page.evaluate(f"window.scrollBy({scroll_x}, {scroll_y})")

            case "keypress":
                keys = action.keys
                for k in keys:
                    print(f"Keypress '{k}'")
                    if k.lower() == "enter":
                        page.keyboard.press("Enter")
                    elif k.lower() == "space":
                        page.keyboard.press(" ")
                    else:
                        page.keyboard.press(k)

            case "type":
                text = action.text
                print(f"Typing text: {text}")
                page.keyboard.type(text)

            case "wait":
                print("Wait")
                time.sleep(2)

            case _:
                print(f"Unrecognized action: {action}")

        return page

    except Exception as e:
        print(f"Error handling action {action}: {e}")
        return page  # keep current page if action failed


def _asks_to_submit(text: str) -> bool:
    """Detect common phrasings where the model asks for submit confirmation."""
    if not text:
        return False
    t = text.lower()
    triggers = [
        "should i go ahead and submit",
        "should i submit",
        "do you want me to submit",
        "am about to submit",
        "ready to submit",
        "proceed with submitting",
        "go ahead and submit it"
    ]
    return any(p in t for p in triggers)

# -----------------------------
# Computer use loop
# -----------------------------
def computer_use_loop(browser, page, response):
    while True:
        # Handle any computer_call(s)
        computer_calls = [item for item in response.output if item.type == "computer_call"]

        # If no computer calls, we may be done OR the model might be asking for confirmation.
        if not computer_calls:
            out_text = getattr(response, "output_text", "") or ""
            if _asks_to_submit(out_text):
                # Auto-confirm inside the loop and continue, so the model issues the submit action next
                print("Model asked for confirmation; auto-confirming: 'Yes, submit the form now.'")
                response = client.responses.create(
                    model="computer-use-preview",
                    previous_response_id=response.id,
                    tools=tools,
                    input=[{
                        "role": "user",
                        "content": "Yes, submit the form now."
                    }],
                    truncation="auto"
                )
                # loop back to process the next computer_call (the actual submit)
                continue

            # Truly done — print the model's final output and break
            print("No more computer calls. Output from model:")
            for item in response.output:
                print(item)
            break

        # Process exactly one computer_call per iteration
        computer_call = computer_calls[0]
        last_call_id = computer_call.call_id
        action = computer_call.action

        # Acknowledge any safety checks on THIS call, per docs
        # (You must pass them back on the very next computer_call_output.)
        pending_safety_checks = getattr(computer_call, "pending_safety_checks", []) or []
        acknowledged_safety_checks = [{"id": sc.id} for sc in pending_safety_checks]
        if acknowledged_safety_checks:
            print("Acknowledging safety checks:", acknowledged_safety_checks)

        # Perform the action in Playwright
        page = handle_model_action(browser, page, action)
        time.sleep(1)

        # Send a screenshot back to the model (and include acknowledgments if present)
        screenshot_bytes = get_screenshot(page)
        screenshot_base64 = base64.b64encode(screenshot_bytes).decode("utf-8")

        input_item = {
            "call_id": last_call_id,
            "type": "computer_call_output",
            "output": {
                "type": "input_image",
                "image_url": f"data:image/png;base64,{screenshot_base64}"
            }
        }
        if acknowledged_safety_checks:
            input_item["acknowledged_safety_checks"] = acknowledged_safety_checks

        response = client.responses.create(
            model="computer-use-preview",
            previous_response_id=response.id,
            tools=tools,
            input=[input_item],
            truncation="auto"
        )

        print("Response: ", response.output)

    return response

# -----------------------------
# Entrypoint
# -----------------------------
def main():
    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=False,
            chromium_sandbox=True,
            env={},
            args=[
                "--disable-extensions",
                "--disable-file-system",
            ]
        )

        page = browser.new_page()
        page.set_viewport_size({"width": 1024, "height": 768})

        # Start on a neutral site to let the model navigate
        page.goto("https://bing.com", wait_until="domcontentloaded")

        # Initial response
        response = client.responses.create(
            model="computer-use-preview",
            input=input_messages,
            tools=tools,
            reasoning={"generate_summary": "concise"},
            truncation="auto"
        )

        print(response.output)

        final_response = computer_use_loop(browser, page, response)
        print("Final response: ", final_response.output_text)

        browser.close()

if __name__ == "__main__":
    main()
