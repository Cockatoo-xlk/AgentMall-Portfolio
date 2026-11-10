/** Per-identity memory only: failed queries must not erase the observed version. */
export class CartReadTracker {
  private sequence = 0
  private watermark: { id: string; version: number } | null = null
  reset() {
    this.sequence++
    this.watermark = null
  }
  begin() {
    return ++this.sequence
  }
  current(read: number) {
    return read === this.sequence
  }
  fail(read: number) {
    if (!this.current(read)) return false
    this.sequence++
    return true
  }
  accept(read: number, next: { id: string; version: number }) {
    if (!this.current(read)) return false
    if (this.watermark?.id === next.id && this.watermark.version > next.version) return false
    this.watermark = { id: next.id, version: next.version }
    return true
  }
  acceptWrite(next: { id: string; version: number }) {
    return this.accept(this.begin(), next)
  }
}
