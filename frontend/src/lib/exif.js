import exifr from "exifr";

// Read GPS from the ORIGINAL file (before resizing, which strips EXIF).
// Returns { lat, lng } or null. Never throws; coordinates are only sent to our own
// backend for the lookup and are never placed in chat messages.
export async function readGps(file) {
  try {
    const gps = await exifr.gps(file);
    if (gps && Number.isFinite(gps.latitude) && Number.isFinite(gps.longitude)) {
      return { lat: gps.latitude, lng: gps.longitude };
    }
  } catch {
    /* no EXIF / unreadable: treat as no GPS */
  }
  return null;
}
