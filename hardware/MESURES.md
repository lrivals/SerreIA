# Cotes à mesurer

À faire avant d'imprimer une pièce définitive (doc 20 §5.2). Chaque cote mesurée va dans
[mesures.toml](mesures.toml) (en mm), qui remplace la valeur nominale de
[params.py](params.py) ; `make hardware` liste celles qui restent nominales.

| Cote (`mesures.toml`) | Nominal | Où mesurer | Outil | Pièces |
|---|---|---|---|---|
| `jeu` | 0,3 | anneaux de jeu imprimés : le plus serré qui glisse sans forcer sur le tube | éprouvette `anneaux_jeu` (encoches = dixièmes) | toutes |
| `tube_d` | 20,0 | tube de structure, à 3 endroits, garder la plus grande (ovalisation) | pied à coulisse | B1, B2, D1, D4 |
| `tube_faitage_d` | 20,0 | tube de faîtage | pied à coulisse | C2 |
| `film_ep` | 0,2 | fiche du film (150–200 µm) | fiche | B2 |
| `cuve_hauteur` | 420 | hauteur intérieure de la cuve | mètre | A4 (garde JSN-SR04T) |
| `cuve_niveau_max` | 160 | hauteur du trop-plein / remplissage maximal | mètre | A4 |
| `sonde_ph_d`, `sonde_ec_d` | 12,0 | corps des sondes, au niveau du passage | pied à coulisse | A4 |
| `ds18b20_d` | 6,0 | gaine étanche de la DS18B20 | pied à coulisse | A4 |
| `jsn_d` | 22,0 | tête du transducteur JSN-SR04T | pied à coulisse | A4 |
| `carte_l`, `carte_w`, `carte_h` | 50 × 30 × 15 | carte porteuse du nœud avec ses borniers | pied à coulisse | D2 |
| `cable_d` | 5,0 | câble de capteur | pied à coulisse | D2 |
| `profile_cote` | 20,0 | montant de lampe (profilé 2020 ou tube carré) | pied à coulisse | C1 |

La garde du JSN-SR04T (`cuve_hauteur - cuve_niveau_max + platine_ep + jsn_rehausse`) doit
rester ≥ 250 mm : sinon augmenter `jsn_rehausse`, que `make hardware` réclame.

Autres cotes réglables sans mesure (même fichier) : `ecart_ph_ec`, `abri_nb_assiettes`,
`clip_largeur`, `etiquette_*`… Toute la liste et les valeurs par défaut sont dans
[params.py](params.py).
