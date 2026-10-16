// Trames du radar Hi-Link HLK-LD2450 (UART 256 000 bauds), lecture continue.
// Trame de données, 30 octets : AA FF 03 00 | 3 cibles x 8 octets | 55 CC.
// Cible : X (int16), Y (int16), vitesse (int16), résolution (uint16), petit-boutiste ;
// signe des coordonnées : bit 15 à 1 = positif, à 0 = négatif. Cible absente : 8 zéros.
#pragma once

#include <cstddef>
#include <cstdint>

namespace serre {

struct Ld2450Target {
  int16_t x_mm;
  int16_t y_mm;
  int16_t speed_cm_s;
  uint16_t resolution_mm;
};

class Ld2450Parser {
 public:
  static constexpr size_t kFrameSize = 30;

  // Un octet reçu ; true quand une trame complète et valide vient d'être décodée.
  bool feed(uint8_t b) {
    static constexpr uint8_t kHeader[4] = {0xAA, 0xFF, 0x03, 0x00};
    if (len_ < 4) {
      if (b == kHeader[len_]) {
        buf_[len_++] = b;
      } else {
        len_ = (b == kHeader[0]) ? 1 : 0;
        if (len_) buf_[0] = b;
      }
      return false;
    }
    buf_[len_++] = b;
    if (len_ < kFrameSize) return false;
    len_ = 0;
    if (buf_[28] != 0x55 || buf_[29] != 0xCC) return false;
    count_ = 0;
    for (int i = 0; i < 3; ++i) {
      const uint8_t* p = buf_ + 4 + 8 * i;
      bool empty = true;
      for (int k = 0; k < 8; ++k) empty = empty && p[k] == 0;
      targets_[i] = {decode(p), decode(p + 2), decode(p + 4),
                     static_cast<uint16_t>(p[6] | (p[7] << 8))};
      if (!empty) ++count_;
    }
    ++frames_;
    return true;
  }

  int count() const { return count_; }  // cibles présentes, 0..3
  const Ld2450Target& target(int i) const { return targets_[i]; }
  uint32_t frames() const { return frames_; }

 private:
  static int16_t decode(const uint8_t* p) {
    uint16_t raw = static_cast<uint16_t>(p[0] | (p[1] << 8));
    int16_t magnitude = static_cast<int16_t>(raw & 0x7FFF);
    return (raw & 0x8000) ? magnitude : static_cast<int16_t>(-magnitude);
  }

  uint8_t buf_[kFrameSize] = {};
  size_t len_ = 0;
  int count_ = 0;
  uint32_t frames_ = 0;
  Ld2450Target targets_[3] = {};
};

}  // namespace serre
