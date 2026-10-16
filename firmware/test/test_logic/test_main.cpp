// Logique pure des nœuds, sur le PC : pio test -e native

#include <unity.h>

#include <cstring>
#include <vector>

#include "command.h"
#include "degraded.h"
#include "ld2450.h"
#include "ranges.h"
#include "soil.h"

using namespace serre;

void setUp() {}
void tearDown() {}

// --- plages ---------------------------------------------------------------------------

void test_quality() {
  TEST_ASSERT_EQUAL_STRING("ok", quality("temperature", 23.4f));
  TEST_ASSERT_EQUAL_STRING("erreur", quality("temperature", 90.0f));
  TEST_ASSERT_EQUAL_STRING("erreur", quality("ph", NAN));
  TEST_ASSERT_EQUAL_STRING("erreur", quality("inconnu", 1.0f));
  TEST_ASSERT_EQUAL_STRING("hPa", findRange("pression")->unite);
}

// --- radar HLK-LD2450 -----------------------------------------------------------------

std::vector<uint8_t> frame(int targets) {
  std::vector<uint8_t> f = {0xAA, 0xFF, 0x03, 0x00};
  for (int i = 0; i < 3; ++i) {
    if (i < targets) {
      // X = -782 mm (bit 15 à 0 : négatif), Y = +1713 mm (bit 15 à 1), vitesse -16, rés. 320
      const uint8_t t[8] = {0x0E, 0x03, 0xB1, 0x86, 0x10, 0x00, 0x40, 0x01};
      f.insert(f.end(), t, t + 8);
    } else {
      f.insert(f.end(), 8, 0x00);
    }
  }
  f.push_back(0x55);
  f.push_back(0xCC);
  return f;
}

int feedAll(Ld2450Parser& p, const std::vector<uint8_t>& bytes) {
  int frames = 0;
  for (uint8_t b : bytes) frames += p.feed(b);
  return frames;
}

void test_ld2450_counts_targets() {
  Ld2450Parser p;
  TEST_ASSERT_EQUAL(1, feedAll(p, frame(2)));
  TEST_ASSERT_EQUAL(2, p.count());
  TEST_ASSERT_EQUAL(-782, p.target(0).x_mm);
  TEST_ASSERT_EQUAL(1713, p.target(0).y_mm);
  TEST_ASSERT_EQUAL(1, feedAll(p, frame(0)));
  TEST_ASSERT_EQUAL(0, p.count());
}

void test_ld2450_resyncs_on_garbage_and_rejects_bad_footer() {
  Ld2450Parser p;
  std::vector<uint8_t> bytes = {0x12, 0xAA, 0x00, 0xAA};  // faux départs
  auto f = frame(3);
  bytes.insert(bytes.end(), f.begin(), f.end());
  TEST_ASSERT_EQUAL(1, feedAll(p, bytes));
  TEST_ASSERT_EQUAL(3, p.count());
  auto bad = frame(1);
  bad[29] = 0x00;
  TEST_ASSERT_EQUAL(0, feedAll(p, bad));
  TEST_ASSERT_EQUAL(3, p.count());  // inchangé
}

// --- commandes ------------------------------------------------------------------------

Verdict parse(const char* json, Command& c) { return parseCommand(json, std::strlen(json), c); }

void test_parse_command() {
  Command c;
  TEST_ASSERT_EQUAL(Verdict::Ok,
                    parse(R"({"ts":"2026-10-12T14:05:00Z","action":"on","valeur":null,)"
                          R"("duree_s":30,"source":"controller","raison":"dec-1 | pH"})", c));
  TEST_ASSERT_TRUE(c.action == Action::On);
  TEST_ASSERT_EQUAL_FLOAT(30.0f, c.duree_s);
  TEST_ASSERT_EQUAL(Verdict::Ok, parse(R"({"action":"pwm","valeur":40})", c));
  TEST_ASSERT_EQUAL_FLOAT(0.4f, level(c));
  TEST_ASSERT_EQUAL(Verdict::Invalid, parse(R"({"action":"pwm"})", c));
  TEST_ASSERT_EQUAL(Verdict::Invalid, parse(R"({"action":"on","valeur":50})", c));
  TEST_ASSERT_EQUAL(Verdict::Invalid, parse(R"({"action":"pwm","valeur":120})", c));
  TEST_ASSERT_EQUAL(Verdict::Invalid, parse(R"({"action":"on","duree_s":0})", c));
  TEST_ASSERT_EQUAL(Verdict::Invalid, parse(R"({"action":"marche"})", c));
  TEST_ASSERT_EQUAL(Verdict::Invalid, parse("pas du json", c));
}

void test_pump_safety() {
  Command c;
  parse(R"({"action":"on"})", c);
  TEST_ASSERT_EQUAL(Verdict::PumpWithoutDuration, checkCommand("pompe_nutri", c, 300, false));
  TEST_ASSERT_EQUAL(Verdict::Ok, checkCommand("ventilo", c, 300, false));
  parse(R"({"action":"on","duree_s":600})", c);
  TEST_ASSERT_EQUAL(Verdict::PumpTooLong, checkCommand("pompe_ph_down", c, 300, false));
  parse(R"({"action":"on","duree_s":30})", c);
  TEST_ASSERT_EQUAL(Verdict::TankEmpty, checkCommand("pompe_nutri_a", c, 300, true));
  TEST_ASSERT_EQUAL(Verdict::Ok, checkCommand("pompe_nutri_a", c, 300, false));
  parse(R"({"action":"off"})", c);
  TEST_ASSERT_EQUAL(Verdict::Ok, checkCommand("pompe_nutri", c, 300, true));  // off toujours
}

// --- mode dégradé, sondes de sol ------------------------------------------------------

void test_degraded_plan() {
  const int hours[] = {7, 13, 19};
  const DegradedPlan p = {hours, 3, 30, 10, 18, 10};
  TEST_ASSERT_TRUE(degradedWater(p, 13, 0, 10));
  TEST_ASSERT_FALSE(degradedWater(p, 13, 0, 40));
  TEST_ASSERT_FALSE(degradedWater(p, 14, 0, 0));
  TEST_ASSERT_TRUE(degradedVent(p, 11, 5));
  TEST_ASSERT_FALSE(degradedVent(p, 11, 15));
  TEST_ASSERT_FALSE(degradedVent(p, 22, 0));
}

void test_soil_percent() {
  TEST_ASSERT_EQUAL_FLOAT(0.0f, soilPercent(2600, 2600, 1100));
  TEST_ASSERT_EQUAL_FLOAT(100.0f, soilPercent(1100, 2600, 1100));
  TEST_ASSERT_EQUAL_FLOAT(50.0f, soilPercent(1850, 2600, 1100));
  TEST_ASSERT_EQUAL_FLOAT(0.0f, soilPercent(2650, 2600, 1100));  // légère dérive bornée
  TEST_ASSERT_EQUAL_STRING("erreur", quality("humidite_sol", soilPercent(3000, 2600, 1100)));
  TEST_ASSERT_EQUAL_STRING("erreur", quality("humidite_sol", soilPercent(1000, 1000, 2000)));
}

int main() {
  UNITY_BEGIN();
  RUN_TEST(test_quality);
  RUN_TEST(test_ld2450_counts_targets);
  RUN_TEST(test_ld2450_resyncs_on_garbage_and_rejects_bad_footer);
  RUN_TEST(test_parse_command);
  RUN_TEST(test_pump_safety);
  RUN_TEST(test_degraded_plan);
  RUN_TEST(test_soil_percent);
  return UNITY_END();
}
