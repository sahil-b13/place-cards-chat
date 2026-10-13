// Resize to max 1024px on the long side and re-encode as JPEG.
// Re-encoding via canvas also strips EXIF (incl. GPS), which is what we want for what we send.
export const MAX_DIMENSION = 1024;
export const MAX_BYTES = 2 * 1024 * 1024; // backend limit per image

export async function resizeToJpeg(file, maxDim = MAX_DIMENSION) {
  const bitmap = await createImageBitmap(file, { imageOrientation: "from-image" });
  const scale = Math.min(1, maxDim / Math.max(bitmap.width, bitmap.height));
  const w = Math.max(1, Math.round(bitmap.width * scale));
  const h = Math.max(1, Math.round(bitmap.height * scale));
  const canvas = document.createElement("canvas");
  canvas.width = w;
  canvas.height = h;
  const ctx = canvas.getContext("2d");
  ctx.fillStyle = "#fff"; // flatten transparency (PNG) onto white
  ctx.fillRect(0, 0, w, h);
  ctx.drawImage(bitmap, 0, 0, w, h);
  bitmap.close?.();

  let blob = null;
  for (const q of [0.85, 0.7, 0.55]) {
    blob = await new Promise((res) => canvas.toBlob(res, "image/jpeg", q));
    if (blob && blob.size <= MAX_BYTES) break;
  }
  if (!blob) throw new Error("Could not process this image");
  if (blob.size > MAX_BYTES) throw new Error("Image is still too large after resizing");
  // keep the base name (cosmetic only; the backend never uses filenames for detection)
  const base = file.name.replace(/\.[^.]+$/, "") || "photo";
  return new File([blob], `${base}.jpg`, { type: "image/jpeg" });
}
