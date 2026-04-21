const updatedDateEl = document.getElementById("updatedDate");

function setUpdatedDate() {
  if (!updatedDateEl) return;
  const text = new Date().toLocaleString("ko-KR", {
    timeZone: "Asia/Seoul",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  });
  updatedDateEl.textContent = `${text} (KST)`;
}

setUpdatedDate();
