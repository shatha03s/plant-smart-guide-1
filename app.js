const form = document.getElementById("chatForm");
const input = document.getElementById("messageInput");
const chat = document.getElementById("chatBox");
const imageInput = document.getElementById("imageInput");
const fileInput = document.getElementById("fileInput");
let selectedImage = null;

function addMessage(text, type = "bot") {
  const div = document.createElement("div");
  div.className = `message ${type}`;
  div.innerText = text;
  chat.appendChild(div);
  chat.scrollTop = chat.scrollHeight;
}

function addTyping() {
  const div = document.createElement("div");
  div.className = "message bot typing";
  div.innerText = "...";
  chat.appendChild(div);
  chat.scrollTop = chat.scrollHeight;
  return div;
}

function handleFile(file) {
  if (!file) return;
  selectedImage = file;
  addMessage(`تم اختيار الصورة: ${file.name}\nاكتبي سؤالك ثم اضغطي إرسال.`, "bot");
}

imageInput?.addEventListener("change", e => handleFile(e.target.files[0]));
fileInput?.addEventListener("change", e => handleFile(e.target.files[0]));

form?.addEventListener("submit", async (e) => {
  e.preventDefault();
  const msg = input.value.trim();
  if (!msg && !selectedImage) return;
  addMessage(msg || "تحليل صورة النبات", "user");
  input.value = "";
  const typing = addTyping();
  try {
    let res;
    if (selectedImage) {
      const formData = new FormData();
      formData.append("message", msg || "حلل صورة النبات");
      formData.append("image", selectedImage);
      res = await fetch("/api/analyze-image", { method: "POST", body: formData });
      selectedImage = null;
      imageInput.value = "";
      fileInput.value = "";
    } else {
      res = await fetch("/api/chat", {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({ message: msg })
      });
    }
    const data = await res.json();
    typing.remove();
    addMessage(data.reply || "لم أتمكن من معالجة الطلب.", "bot");
  } catch (err) {
    typing.remove();
    addMessage("حدث خلل مؤقت. أعيدي المحاولة.", "bot");
  }
});
