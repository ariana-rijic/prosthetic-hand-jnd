"""
Aplikacija za ispitivanje vizuelnog razlikovanja brzine zatvaranja.

Prva verzija diplomskog projekta:
- prikazuje dva virtuelna zatvaranja sake;
- ispitanik bira koje zatvaranje je bilo brze;
- koristi adaptivno pravilo 1 gore / 2 dolje;
- izracunava najmanju primetnu razliku (JND);
- prikazuje grafikon toka razlike brzina i promene smera;
- cuva svaki odgovor u CSV datoteku.

"""

import csv
import math
import random
import re
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
import tkinter as tk
from tkinter import messagebox, ttk

try:
    import serial
except ImportError:
    serial = None


# -----------------------------------------------------------------------------
# POSTAVKE EKSPERIMENTA
# -----------------------------------------------------------------------------

STANDARDNA_BRZINA = 50       # fiksna brzina, izrazena u procentima
POCETNA_RAZLIKA = 15         # uporedna brzina na pocetku je 50 + 15 = 65%
# Korak se smanjuje posle svake promene smera dok se ne dostigne
# poslednja (najmanja) vrednost, koja onda vredi do kraja testa.
KORACI_PROMJENE = (4, 2, 1)
MINIMALNA_RAZLIKA = 1
MAKSIMALNA_BRZINA = 100
BROJ_PROMJENA_SMJERA = 5
# Prva promena se izostavlja jer ispitanik tada jos prilagodjava odgovore.
BROJ_PROMJENA_ZA_JND = 4

BROJ_PROBNIH_POKUSAJA = 5
PROBNA_RAZLIKA = 25          # u probnoj fazi razlika je namerno velika

PAUZA_IZMEDJU_STIMULUSA_MS = 750
PAUZA_POSLIJE_ODGOVORA_MS = 650
# Kratka pauza posle "Odgovor je zabelezen" a pre prvog stimulusa narednog
# pokusaja, da ispitanik ne predje odmah iz odgovora u novi stimulus.
PAUZA_PRIJE_PRVOG_STIMULUSA_MS = 300
BRZINA_OSVJEZAVANJA_MS = 16
# Mnozilac trajanja zatvaranja stvarne proteze — podize se ako je stvarnoj
# protezi potrebno vise vremena da zavrsi pokret nego sto racunica inace
# predvidja. Ne uticje na virtuelnu animaciju (vidi FAKTOR_TRAJANJA_VIRTUELNO).
FAKTOR_TRAJANJA_ZATVARANJA = 2.5
# Mnozilac trajanja virtuelne animacije zatvaranja na ekranu.
FAKTOR_TRAJANJA_VIRTUELNO = 1.5
# Brzina kojom se saka vraca u otvorenu poziciju izmedju stimulusa (0-100%).
# Namerno manja od maksimuma da otvaranje ne deluje naglo ispitaniku.
BRZINA_OTVARANJA = 50




FONT_PORODICA = "Segoe UI"

BOJA_POZADINA = "#eceff5"          # hladna svijetla podloga prozora
BOJA_KARTICA = "#ffffff"           # povrsina kartica
BOJA_SENKA = "#c3ccdb"            # lazna senka ispod kartica
BOJA_OKVIR = "#dbe1ec"            # tanke ivice kartica i polja

BOJA_AKCENT = "#4338ca"           # primarni akcenat (indigo)
BOJA_AKCENT_TAMNA = "#3730a3"     # hover / pritisnuto stanje
BOJA_AKCENT_TINTA = "#eef2ff"     # blaga popuna u akcentnoj boji

BOJA_USPEH = "#0d9488"            # tacan odgovor (tirkizna)
BOJA_GRESKA = "#dc2626"           # netacan odgovor / prekid

BOJA_TEKST = "#1e293b"            # glavni tekst
BOJA_TEKST_MEKI = "#516079"       # sekundarni tekst
BOJA_TEKST_NA_AKCENTU = "#ffffff"

BOJA_PRST_A = "#4338ca"           # prvi prst u animaciji (indigo)
BOJA_PRST_A_MEKA = "#e0e7ff"
BOJA_PRST_B = "#d97706"           # drugi prst u animaciji (amber)
BOJA_PRST_B_MEKA = "#fef3c7"


# -----------------------------------------------------------------------------
# POVEZIVANJE SA PROTEZOM (Bluetooth SPP, Otto Bock Standard Frame)
#
# Otvaranje i zatvaranje sake se salju automatski, usklajdjeno sa prikazom
# stimulusa na ekranu (nije potrebna nikakva rucna radnja ispitivaca) — ovako
# proteza uvek pokazuje istu brzinu koja se u tom trenutku prikazuje i na
# ekranu.
# -----------------------------------------------------------------------------

POVEZATI_PROTEZU = True   # staviti na False za rad bez fizicke proteze (npr. razvoj/testiranje)
# "AUTO" = program sam pronadje Bluetooth COM port proteze (radi ako je uparen
# tacno jedan Bluetooth SPP uredjaj). Ako ih ima vise, ovde upisati konkretan
# port, npr. "COM7" (vidi Device Manager > Ports, ili listu koju program ispise).
PROTEZA_COM_PORT = "COM4"  # rucno upisan port (ako COM3 ne radi, probati "COM4")
PROTEZA_BAUDRATE = 115200
# Otvaranje COM porta samo po sebi NE znaci da je proteza tu — na racunaru
# mogu postojati i virtuelni/legacy COM portovi koji se uredno otvore. Zato
# trazimo da izabrani port bude stvarna Bluetooth SPP veza (hwid "BTHENUM").
# Staviti na False samo ako se proteza povezuje preko USB serijskog adaptera.
PROTEZA_ZAHTEVAJ_BLUETOOTH = True
PROTEZA_MAKSIMALNA_BRZINA = 1023  # gornja granica hardverske brzine


def nadji_com_portove():
    """Vraca listu (device, description, hwid) svih COM portova."""
    try:
        from serial.tools import list_ports
    except ImportError:
        return []
    return [(p.device, p.description, (p.hwid or "")) for p in list_ports.comports()]


def nadji_bluetooth_portove():
    """Vraca listu (device, description) portova koji su Bluetooth SPP veze."""
    return [
        (dev, opis)
        for dev, opis, hwid in nadji_com_portove()
        if "BTHENUM" in hwid.upper()
    ]


def spisak_portova_tekst():
    """Citljiv spisak svih COM portova, za poruke o gresci."""
    portovi = nadji_com_portove()
    if not portovi:
        return "Nije pronadjen nijedan COM port."
    return "\n".join(f"  - {dev}: {opis}" for dev, opis, _ in portovi)


# Ispitanik bira jedan od dva medjusobno iskljuciva nacina ispitivanja: ili
# gleda samo animaciju na ekranu (proteza se uopste ne pokrece), ili
# posmatra stvarnu protezu koja se fizicki zatvara/otvara (ekran u tom
# slucaju ne prikazuje animaciju, kako ispitanik ne bi imao dva istovremena
# izvora informacije o brzini).
NACIN_VIRTUELNO = "virtuelno"
NACIN_STVARNO = "stvarno"
NAZIV_NACINA_VIRTUELNO = "Virtuelno ispitivanje (animacija na ekranu)"
NAZIV_NACINA_STVARNO = "Stvarno ispitivanje (sa protezom)"

# Vrijednosti iz Otto Bock protokola su uklonjene jer je protokol povjerljiv.
PROTEZA_CMD_MANUAL_MOVE = None
PROTEZA_MOTION_STOP = None
PROTEZA_MOTION_ZATVORI = None
PROTEZA_MOTION_OTVORI = None
PROTEZA_MOTION_NEUTRALNO = None


class KontrolerProteze:
    """Salje komande za otvaranje/zatvaranje sake protezi.
    """

    def __init__(self, port, baudrate):
        self.port = port
        self.baudrate = baudrate
        self.veza = None
        self.razlog_neuspeha = ""

    def _provjeri_bluetooth_port(self):
        """Vraca (ok, poruka). Podrzava PROTEZA_COM_PORT = "AUTO" (sam nadje
        Bluetooth port) i proverava da izabrani port stvarno postoji i da je
        Bluetooth SPP veza (osim ako je PROTEZA_ZAHTEVAJ_BLUETOOTH False)."""
        svi = nadji_com_portove()
        if not svi:
            return True, ""  # nema pyserial-a ili nema portova — pustamo dalje

        bt = nadji_bluetooth_portove()

        # AUTO: automatski izbor Bluetooth porta.
        if str(self.port).strip().upper() in ("", "AUTO"):
            if len(bt) == 1:
                self.port = bt[0][0]
                print(f"Proteza: automatski izabran port {self.port} ({bt[0][1]})")
                return True, ""
            if not bt:
                return False, (
                    "Nije pronadjen nijedan Bluetooth COM port. Uparite protezu "
                    "preko Bluetooth-a, pa pokusajte ponovo.\n\n"
                    "Pronadjeni portovi:\n" + spisak_portova_tekst()
                )
            spisak_bt = "\n".join(f"  - {dev}: {opis}" for dev, opis in bt)
            return False, (
                "Pronadjeno je vise Bluetooth portova, ne mogu sam da izaberem. "
                "Upisite tacan port u PROTEZA_COM_PORT:\n" + spisak_bt
            )

        # Rucno zadat port.
        po_imenu = {dev.upper(): opis for dev, opis, _ in svi}
        if self.port.upper() not in po_imenu:
            return False, (
                f"Port {self.port} ne postoji na ovom racunaru.\n\n"
                "Pronadjeni portovi:\n" + spisak_portova_tekst()
            )
        if PROTEZA_ZAHTEVAJ_BLUETOOTH and self.port.upper() not in {
            dev.upper() for dev, _ in bt
        }:
            spisak_bt = (
                "\n".join(f"  - {dev}: {opis}" for dev, opis in bt)
                if bt else "  (nijedan)"
            )
            return False, (
                f"Port {self.port} nije Bluetooth veza sa protezom "
                f"(otkriveno: {po_imenu[self.port.upper()]}).\n\n"
                "Bluetooth portovi na ovom racunaru:\n" + spisak_bt
            )
        return True, ""

    def povezi(self):
        self.razlog_neuspeha = ""
        if serial is None:
            self.razlog_neuspeha = (
                "Modul 'pyserial' nije instaliran (pip install pyserial)."
            )
            print(self.razlog_neuspeha)
            return False

        ok, poruka = self._provjeri_bluetooth_port()
        if not ok:
            self.razlog_neuspeha = poruka
            print(poruka)
            return False

        try:
            self.veza = serial.Serial(self.port, self.baudrate, timeout=0)
        except serial.SerialException as greska:
            self.razlog_neuspeha = (
                f"Otvaranje porta {self.port} nije uspelo: {greska}\n"
                "Proverite da li je proteza upaljena i uparena."
            )
            print(self.razlog_neuspeha)
            self.veza = None
            return False

        # Kratka provera da druga strana zaista prima podatke: saljemo STOP.
        try:
            self.veza.write(self._napravi_okvir([PROTEZA_MOTION_STOP, 0]))
        except Exception as greska:
            self.razlog_neuspeha = (
                f"Proteza ne odgovara na portu {self.port}: {greska}"
            )
            print(self.razlog_neuspeha)
            self.zatvori_vezu()
            return False
        return True

    def povezana(self):
        return self.veza is not None and self.veza.is_open

    def zatvori_vezu(self):
        if self.veza is not None:
            try:
                self.veza.close()
            except Exception:
                pass
            self.veza = None

    @staticmethod
    def _napravi_okvir(bajtovi_podataka):
        # Format okvira iz Otto Bock protokola je uklonjen jer je protokol povjerljiv.
        raise NotImplementedError("Format okvira nije javno dostupan.")

    def _posalji_manual_move(self, motion_id, brzina):
        if not self.povezana():
            return
        brzina = max(0, min(PROTEZA_MAKSIMALNA_BRZINA, int(round(brzina))))
        # Raspored bajtova komande je uklonjen jer je protokol povjerljiv.
        okvir = self._napravi_okvir([motion_id, brzina])

        try:
            self.veza.write(okvir)
        except Exception as greska:
            print(f"Greska pri slanju komande protezi: {greska}")

    def zatvori_saku(self, brzina_procenat):
        """Pokrece zatvaranje sake brzinom izrazenom u procentima (0-100)."""
        hw_brzina = brzina_procenat / 100 * PROTEZA_MAKSIMALNA_BRZINA
        self._posalji_manual_move(PROTEZA_MOTION_ZATVORI, hw_brzina)

    def otvori_saku(self, brzina_procenat=100):
        """Vraca saku u otvorenu poziciju (reset pre sledeceg zatvaranja)."""
        hw_brzina = brzina_procenat / 100 * PROTEZA_MAKSIMALNA_BRZINA
        self._posalji_manual_move(PROTEZA_MOTION_OTVORI, hw_brzina)

    def neutralna_pozicija(self):
        self._posalji_manual_move(
            PROTEZA_MOTION_NEUTRALNO, PROTEZA_MAKSIMALNA_BRZINA
        )

    def zaustavi(self):
        self._posalji_manual_move(PROTEZA_MOTION_STOP, 0)


@dataclass
class RezultatKoraka:
    """Rezultat jednog azuriranja stepenastog postupka."""

    razlika_prije: int
    razlika_poslije: int
    smjer: str
    promjena_smjera: bool
    broj_promjena_smjera: int
    zavrsen_test: bool


class StepenastiPostupak:
    """Transformisani postupak 1 gore / 2 dolje za procenu JND-a."""

    def __init__(self):
        self.razlika = POCETNA_RAZLIKA
        self.uzastopno_tacnih = 0
        self.prethodni_smjer = None
        self.promjene_smjera = []
        self.tacnih_na_minimumu = 0
        self.zavrsen = False
        self.razlog_zavrsetka = ""

    @property
    def uporedna_brzina(self):
        return min(STANDARDNA_BRZINA + self.razlika, MAKSIMALNA_BRZINA)

    def trenutni_korak(self):
        """Korak se smanjuje sa svakom novom promenom smera (vidi KORACI_PROMJENE)."""
        indeks = min(len(self.promjene_smjera), len(KORACI_PROMJENE) - 1)
        return KORACI_PROMJENE[indeks]

    def obradi_odgovor(self, tacan_odgovor):
        razlika_prije = self.razlika
        korak = self.trenutni_korak()
        novi_smjer = "bez promene"

        if tacan_odgovor:
            self.uzastopno_tacnih += 1

            if razlika_prije == MINIMALNA_RAZLIKA:
                self.tacnih_na_minimumu += 1
            else:
                self.tacnih_na_minimumu = 0

            # Tek posle dva uzastopna tacna odgovora smanjujemo razliku.
            if self.uzastopno_tacnih >= 2:
                nova_razlika = max(
                    MINIMALNA_RAZLIKA,
                    razlika_prije - korak,
                )
                self.uzastopno_tacnih = 0
                if nova_razlika != razlika_prije:
                    novi_smjer = "smanjenje"
                    self.razlika = nova_razlika
        else:
            self.uzastopno_tacnih = 0
            self.tacnih_na_minimumu = 0
            maksimalna_razlika = MAKSIMALNA_BRZINA - STANDARDNA_BRZINA
            nova_razlika = min(
                maksimalna_razlika,
                razlika_prije + korak,
            )
            if nova_razlika != razlika_prije:
                novi_smjer = "povecanje"
                self.razlika = nova_razlika

        jeste_promjena_smjera = False
        if novi_smjer != "bez promene":
            if (
                self.prethodni_smjer is not None
                and novi_smjer != self.prethodni_smjer
            ):
                # Belezimo vrednost na kojoj je doslo do promene smera.
                self.promjene_smjera.append(razlika_prije)
                jeste_promjena_smjera = True
            self.prethodni_smjer = novi_smjer

        if len(self.promjene_smjera) >= BROJ_PROMJENA_SMJERA:
            self.zavrsen = True
            self.razlog_zavrsetka = (
                f"Dostignuto je {BROJ_PROMJENA_SMJERA} promena smera."
            )
        elif self.tacnih_na_minimumu >= 7:
            self.zavrsen = True
            self.razlog_zavrsetka = (
                "Minimalna razlika od 1% prepoznata je 7 puta."
            )

        return RezultatKoraka(
            razlika_prije=razlika_prije,
            razlika_poslije=self.razlika,
            smjer=novi_smjer,
            promjena_smjera=jeste_promjena_smjera,
            broj_promjena_smjera=len(self.promjene_smjera),
            zavrsen_test=self.zavrsen,
        )

    def izracunaj_jnd(self):
        if self.tacnih_na_minimumu >= 7:
            return float(MINIMALNA_RAZLIKA)

        vrijednosti = self.promjene_smjera[-BROJ_PROMJENA_ZA_JND:]
        if not vrijednosti:
            return float(self.razlika)
        return sum(vrijednosti) / len(vrijednosti)


class Aplikacija:
    def __init__(self, root):
        self.root = root
        self.root.title("Test vizuelnog razlikovanja brzine")
        self.root.geometry("1040x780")
        self.root.minsize(960, 700)
        self.root.configure(bg=BOJA_POZADINA)

        self.stil = ttk.Style()
        self.stil.theme_use("clam")
        self.podesi_stilove()

        self.napravi_zaglavlje()

        self.glavni_okvir = ttk.Frame(
            root, style="Pozadina.TFrame", padding=(34, 24)
        )
        self.glavni_okvir.pack(fill="both", expand=True)

        self.podaci_ispitanika = {}
        self.redovi_za_csv = []
        self.putanja_csv = None
        self.faza = ""
        self.broj_pokusaja = 0
        self.broj_probnog_pokusaja = 0
        self.trenutne_brzine = []
        self.tacan_odgovor = None
        self.vrijeme_pocetka_odgovora = None
        self.stepenasti = None
        self.animacija_u_toku = False
        self.ispitivanje_prekinuto = False
        self.zakazani_poslovi = set()

        self.nacin_ispitivanja = None
        self.proteza = KontrolerProteze(PROTEZA_COM_PORT, PROTEZA_BAUDRATE)

        self.root.bind("<Key-1>", lambda event: self.zabiljezi_odgovor(1))
        self.root.bind("<Key-2>", lambda event: self.zabiljezi_odgovor(2))
        self.root.protocol("WM_DELETE_WINDOW", self.zatvori_aplikaciju)

        self.prikazi_unos_podataka()

    def zatvori_aplikaciju(self):
        """Otkazuje zakazane after() pozive pre zatvaranja prozora (npr. na X dugme)."""
        self.ispitivanje_prekinuto = True
        self.otkazi_zakazane_poslove()
        self.proteza.zaustavi()
        self.proteza.zatvori_vezu()
        self.root.destroy()

    def podesi_stilove(self):
        self.stil.configure("Pozadina.TFrame", background=BOJA_POZADINA)

        self.stil.configure(
            "Naslov.TLabel",
            background=BOJA_POZADINA,
            foreground=BOJA_TEKST,
            font=(FONT_PORODICA, 22, "bold"),
        )
        self.stil.configure(
            "Podnaslov.TLabel",
            background=BOJA_POZADINA,
            foreground=BOJA_TEKST_MEKI,
            font=(FONT_PORODICA, 11),
        )
        self.stil.configure(
            "Tekst.TLabel",
            background=BOJA_POZADINA,
            foreground=BOJA_TEKST,
            font=(FONT_PORODICA, 11),
        )
        self.stil.configure(
            "Status.TLabel",
            background=BOJA_POZADINA,
            foreground=BOJA_AKCENT,
            font=(FONT_PORODICA, 11, "bold"),
        )

        # --- Dugmad -------------------------------------------------------
        self.stil.configure(
            "Primarno.TButton",
            font=(FONT_PORODICA, 12, "bold"),
            foreground=BOJA_TEKST_NA_AKCENTU,
            background=BOJA_AKCENT,
            borderwidth=0,
            padding=(26, 14),
        )
        self.stil.map(
            "Primarno.TButton",
            background=[("active", BOJA_AKCENT_TAMNA), ("disabled", "#b9c0d0")],
            foreground=[("disabled", "#eef1f6")],
        )

        self.stil.configure(
            "Odgovor.TButton",
            font=(FONT_PORODICA, 13, "bold"),
            foreground=BOJA_TEKST_NA_AKCENTU,
            background=BOJA_AKCENT,
            borderwidth=0,
            padding=(30, 18),
        )
        self.stil.map(
            "Odgovor.TButton",
            background=[("active", BOJA_AKCENT_TAMNA), ("disabled", "#b9c0d0")],
            foreground=[("disabled", "#eef1f6")],
        )

        self.stil.configure(
            "Sekundarno.TButton",
            font=(FONT_PORODICA, 11, "bold"),
            foreground=BOJA_AKCENT,
            background=BOJA_KARTICA,
            bordercolor=BOJA_AKCENT,
            borderwidth=1,
            padding=(22, 12),
        )
        self.stil.map(
            "Sekundarno.TButton",
            background=[("active", BOJA_AKCENT_TINTA)],
            foreground=[("disabled", "#9aa3b2")],
        )

        self.stil.configure(
            "Prekid.TButton",
            font=(FONT_PORODICA, 10, "bold"),
            foreground="white",
            background=BOJA_GRESKA,
            borderwidth=0,
            padding=(18, 10),
        )
        self.stil.map(
            "Prekid.TButton",
            background=[("active", "#991b1b"), ("disabled", "#cbd5e1")],
        )

        # --- Polja i traka napretka ------------------------------------
        self.stil.configure(
            "TEntry", padding=8, fieldbackground="#ffffff", bordercolor=BOJA_OKVIR
        )
        self.stil.configure(
            "TCombobox", padding=7, fieldbackground="#ffffff",
            bordercolor=BOJA_OKVIR,
        )
        self.stil.configure(
            "Traka.Horizontal.TProgressbar",
            troughcolor=BOJA_OKVIR,
            bordercolor=BOJA_OKVIR,
            background=BOJA_AKCENT,
            lightcolor=BOJA_AKCENT,
            darkcolor=BOJA_AKCENT,
            thickness=10,
        )

    def napravi_zaglavlje(self):
        """Trajna obojena traka na vrhu prozora (ostaje kroz sve ekrane)."""
        zaglavlje = tk.Frame(self.root, bg=BOJA_AKCENT, height=66)
        zaglavlje.pack(fill="x", side="top")
        zaglavlje.pack_propagate(False)
        tk.Frame(self.root, bg=BOJA_AKCENT_TAMNA, height=3).pack(
            fill="x", side="top"
        )

        amblem = tk.Canvas(
            zaglavlje, width=44, height=44, bg=BOJA_AKCENT, highlightthickness=0
        )
        amblem.pack(side="left", padx=(26, 14))
        for pomak in (0, 12):
            amblem.create_line(
                9 + pomak, 12, 21 + pomak, 22, 9 + pomak, 32,
                fill=BOJA_TEKST_NA_AKCENTU, width=4,
                capstyle="round", joinstyle="round",
            )

        tk.Label(
            zaglavlje,
            text="TEST VIZUELNOG RAZLIKOVANJA BRZINE",
            bg=BOJA_AKCENT,
            fg=BOJA_TEKST_NA_AKCENTU,
            font=(FONT_PORODICA, 14, "bold"),
        ).pack(side="left")

    def napravi_karticu(self, roditelj, popuna=22):
        
        senka = tk.Frame(roditelj, bg=BOJA_SENKA)
        karta = tk.Frame(
            senka,
            bg=BOJA_KARTICA,
            highlightbackground=BOJA_OKVIR,
            highlightthickness=1,
        )
        karta.pack(fill="both", expand=True, padx=(0, 4), pady=(0, 4))
        unutra = tk.Frame(karta, bg=BOJA_KARTICA)
        unutra.pack(fill="both", expand=True, padx=popuna, pady=popuna)
        return senka, unutra

    def obrisi_sadrzaj(self):
        for element in self.glavni_okvir.winfo_children():
            element.destroy()

    def zakazi(self, kasnjenje_ms, funkcija):
        """Zakazuje funkciju i pamti je da bi se mogla otkazati pri prekidu."""
        identifikator = None

        def pozovi_funkciju():
            self.zakazani_poslovi.discard(identifikator)
            if not self.ispitivanje_prekinuto:
                funkcija()

        identifikator = self.root.after(kasnjenje_ms, pozovi_funkciju)
        self.zakazani_poslovi.add(identifikator)
        return identifikator

    def otkazi_zakazane_poslove(self):
        for identifikator in list(self.zakazani_poslovi):
            try:
                self.root.after_cancel(identifikator)
            except tk.TclError:
                pass
        self.zakazani_poslovi.clear()

    # ------------------------------------------------------------------
    # EKRAN 1: podaci o ispitaniku
    # ------------------------------------------------------------------

    def prikazi_unos_podataka(self):
        self.obrisi_sadrzaj()

        ttk.Label(
            self.glavni_okvir,
            text="Test vizuelnog razlikovanja brzine",
            style="Naslov.TLabel",
        ).pack(pady=(14, 22))

        senka, karta = self.napravi_karticu(self.glavni_okvir, popuna=26)
        senka.pack(padx=170, fill="x")
        karta.columnconfigure(1, weight=1)

        tk.Label(
            karta,
            text="Podaci o ispitaniku",
            bg=BOJA_KARTICA,
            fg=BOJA_TEKST,
            font=(FONT_PORODICA, 13, "bold"),
        ).grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 14))

        def natpis_polja(red, tekst):
            tk.Label(
                karta,
                text=tekst,
                bg=BOJA_KARTICA,
                fg=BOJA_TEKST_MEKI,
                font=(FONT_PORODICA, 10, "bold"),
            ).grid(row=red, column=0, sticky="w", padx=(0, 16), pady=8)

        natpis_polja(1, "Ime ispitanika")
        self.unos_imena = ttk.Entry(karta, width=32)
        self.unos_imena.grid(row=1, column=1, sticky="ew", pady=8)

        natpis_polja(2, "Godine")
        self.unos_godina = ttk.Entry(karta, width=32)
        self.unos_godina.grid(row=2, column=1, sticky="ew", pady=8)

        natpis_polja(3, "Dominantna ruka")
        self.izbor_ruke = ttk.Combobox(
            karta, values=["Desna", "Leva"], state="readonly"
        )
        self.izbor_ruke.grid(row=3, column=1, sticky="ew", pady=8)

        natpis_polja(4, "Korekcija vida")
        self.izbor_vida = ttk.Combobox(
            karta,
            values=["Bez korekcije", "Naocare", "Kontaktna sociva"],
            state="readonly",
        )
        self.izbor_vida.grid(row=4, column=1, sticky="ew", pady=8)

        natpis_polja(5, "Nacin ispitivanja")
        self.izbor_nacina = ttk.Combobox(
            karta,
            values=[NAZIV_NACINA_VIRTUELNO, NAZIV_NACINA_STVARNO],
            state="readonly",
        )
        self.izbor_nacina.grid(row=5, column=1, sticky="ew", pady=8)

        ttk.Button(
            self.glavni_okvir,
            text="NASTAVI",
            style="Primarno.TButton",
            command=self.provjeri_podatke,
        ).pack(pady=26)

    def provjeri_podatke(self):
        ime = self.unos_imena.get().strip()
        godine = self.unos_godina.get().strip()
        ruka = self.izbor_ruke.get()
        vid = self.izbor_vida.get()
        naziv_nacina = self.izbor_nacina.get()

        if not ime or not godine or not ruka or not vid or not naziv_nacina:
            messagebox.showwarning(
                "Nedostaju podaci",
                "Potrebno je popuniti sva polja.",
            )
            return

        if not godine.isdigit() or not 10 <= int(godine) <= 90:
            messagebox.showwarning(
                "Neispravne godine",
                "Unesite ispravan broj godina.",
            )
            return

        self.nacin_ispitivanja = (
            NACIN_STVARNO
            if naziv_nacina == NAZIV_NACINA_STVARNO
            else NACIN_VIRTUELNO
        )

        if self.nacin_ispitivanja == NACIN_STVARNO and POVEZATI_PROTEZU:
            if not self.proteza.povezi():
                messagebox.showerror(
                    "Proteza nije povezana",
                    (self.proteza.razlog_neuspeha or
                     f"Povezivanje na port {PROTEZA_COM_PORT} nije uspelo.")
                    + "\n\nStvarno ispitivanje nije moguce zapoceti bez "
                    "povezane proteze.",
                )
                return

        self.podaci_ispitanika = {
            "ime_ispitanika": ime,
            "godine": int(godine),
            "dominantna_ruka": ruka,
            "korekcija_vida": vid,
            "nacin_ispitivanja": self.nacin_ispitivanja,
        }
        self.pripremi_csv_datoteku()
        self.prikazi_uputstvo()

    # ------------------------------------------------------------------
    # EKRAN 2: uputstvo
    # ------------------------------------------------------------------

    def prikazi_uputstvo(self):
        self.obrisi_sadrzaj()

        ttk.Label(
            self.glavni_okvir,
            text="Uputstvo za ispitanika",
            style="Naslov.TLabel",
        ).pack(pady=(24, 18))

        if self.nacin_ispitivanja == NACIN_STVARNO:
            opis_stimulusa = (
                "U svakom pokusaju proteza ce dva puta uzastopno zatvoriti "
                "saku.\n\n"
            )
        else:
            opis_stimulusa = (
                "U svakom pokusaju bice prikazana dva uzastopna zatvaranja "
                "virtuelne sake.\n\n"
            )

        uputstvo = (
            opis_stimulusa
            + "Vas zadatak je da odredite koje zatvaranje je bilo brze. "
            "Nakon prikazivanja izaberite PRVO ili DRUGO.\n\n"
            "Na pocetku sledi pet probnih pokusaja. U njima cete dobiti "
            "obavestenje da li je odgovor tacan. U glavnom testu povratna "
            "informacija se nece prikazivati.\n\n"
            "Mozete koristiti dugmad na ekranu ili tastere 1 i 2."
        )
        senka, karta = self.napravi_karticu(self.glavni_okvir, popuna=28)
        senka.pack(padx=110, fill="x")
        tk.Label(
            karta,
            text=uputstvo,
            bg=BOJA_KARTICA,
            fg=BOJA_TEKST,
            font=(FONT_PORODICA, 11),
            justify="left",
            wraplength=640,
        ).pack(anchor="w")

        ttk.Button(
            self.glavni_okvir,
            text="POKRENI PROBNU FAZU",
            style="Primarno.TButton",
            command=self.pokreni_probnu_fazu,
        ).pack(pady=24)

    # ------------------------------------------------------------------
    # EKRAN EKSPERIMENTA
    # ------------------------------------------------------------------

    def napravi_ekran_eksperimenta(self):
        self.obrisi_sadrzaj()

        self.oznaka_faze = ttk.Label(
            self.glavni_okvir,
            text="",
            style="Naslov.TLabel",
        )
        self.oznaka_faze.pack(pady=(0, 4))

        self.oznaka_statusa = ttk.Label(
            self.glavni_okvir,
            text="Pripremite se...",
            style="Status.TLabel",
        )
        self.oznaka_statusa.pack(pady=(0, 8))

        self.traka_napretka = ttk.Progressbar(
            self.glavni_okvir,
            style="Traka.Horizontal.TProgressbar",
            length=760,
            mode="determinate",
            maximum=100,
        )
        self.traka_napretka.pack(pady=(0, 12))

        senka, karta = self.napravi_karticu(self.glavni_okvir, popuna=0)
        senka.pack()
        self.canvas = tk.Canvas(
            karta,
            width=760,
            height=380,
            bg=BOJA_KARTICA,
            highlightthickness=0,
        )
        self.canvas.pack()

        self.okvir_odgovora = ttk.Frame(
            self.glavni_okvir,
            style="Pozadina.TFrame",
        )
        self.okvir_odgovora.pack(pady=18)

        self.dugme_prvo = ttk.Button(
            self.okvir_odgovora,
            text="1  —  PRVO JE BILO BRZE",
            style="Odgovor.TButton",
            command=lambda: self.zabiljezi_odgovor(1),
        )
        self.dugme_prvo.grid(row=0, column=0, padx=14)

        self.dugme_drugo = ttk.Button(
            self.okvir_odgovora,
            text="2  —  DRUGO JE BILO BRZE",
            style="Odgovor.TButton",
            command=lambda: self.zabiljezi_odgovor(2),
        )
        self.dugme_drugo.grid(row=0, column=1, padx=14)
        self.omoguci_odgovore(False)

        self.dugme_prekinuti = ttk.Button(
            self.glavni_okvir,
            text="PREKINI ISPITIVANJE I PRIKAZI REZULTATE",
            style="Prekid.TButton",
            command=self.prekini_ispitivanje,
        )
        self.dugme_prekinuti.pack(pady=(0, 8))

    def pokreni_probnu_fazu(self):
        self.ispitivanje_prekinuto = False
        self.faza = "probna"
        self.broj_probnog_pokusaja = 0
        self.napravi_ekran_eksperimenta()
        self.oznaka_faze.config(text="Probna faza")
        self.traka_napretka.config(maximum=BROJ_PROBNIH_POKUSAJA, value=0)
        if self.nacin_ispitivanja == NACIN_STVARNO:
            self.proteza.neutralna_pozicija()
        self.zakazi(700, self.sljedeci_probni_pokusaj)

    def sljedeci_probni_pokusaj(self):
        if self.broj_probnog_pokusaja >= BROJ_PROBNIH_POKUSAJA:
            self.prikazi_pocetak_glavnog_testa()
            return

        self.broj_probnog_pokusaja += 1
        uporedna = STANDARDNA_BRZINA + PROBNA_RAZLIKA
        self.pripremi_pokusaj(STANDARDNA_BRZINA, uporedna)
        self.traka_napretka.config(value=self.broj_probnog_pokusaja)
        self.oznaka_statusa.config(
            text=(
                f"Probni pokusaj {self.broj_probnog_pokusaja} od "
                f"{BROJ_PROBNIH_POKUSAJA}"
            )
        )
        self.pokreni_prikaz_dva_stimulusa()

    def prikazi_pocetak_glavnog_testa(self):
        self.omoguci_odgovore(False)
        self.canvas.delete("all")
        self.oznaka_statusa.config(
            text=(
                "Probna faza je zavrsena. U glavnom testu nece biti "
                "prikazana tacnost odgovora."
            )
        )
        self.oznaka_faze.config(text="Glavni test")
        self.traka_napretka.config(maximum=BROJ_PROMJENA_SMJERA, value=0)
        ttk.Button(
            self.okvir_odgovora,
            text="POKRENI GLAVNI TEST",
            style="Primarno.TButton",
            command=self.pokreni_glavni_test,
        ).grid(row=1, column=0, columnspan=2, pady=15)

    def pokreni_glavni_test(self):
        for element in self.okvir_odgovora.grid_slaves(row=1):
            element.destroy()

        self.faza = "glavna"
        self.broj_pokusaja = 0
        self.stepenasti = StepenastiPostupak()
        self.sljedeci_glavni_pokusaj()

    def sljedeci_glavni_pokusaj(self):
        if self.stepenasti.zavrsen:
            self.zavrsi_test()
            return

        self.broj_pokusaja += 1
        self.pripremi_pokusaj(
            STANDARDNA_BRZINA,
            self.stepenasti.uporedna_brzina,
        )
        self.traka_napretka.config(value=len(self.stepenasti.promjene_smjera))
        self.oznaka_statusa.config(
            text=(
                f"Pokusaj {self.broj_pokusaja}  |  "
                f"Promene smera: "
                f"{len(self.stepenasti.promjene_smjera)}/"
                f"{BROJ_PROMJENA_SMJERA}"
            )
        )
        self.pokreni_prikaz_dva_stimulusa()

    def pripremi_pokusaj(self, standardna, uporedna):
        self.trenutne_brzine = [standardna, uporedna]
        random.shuffle(self.trenutne_brzine)
        self.tacan_odgovor = (
            1 if self.trenutne_brzine[0] > self.trenutne_brzine[1] else 2
        )

    def pokreni_prikaz_dva_stimulusa(self):
        self.omoguci_odgovore(False)
        self.animacija_u_toku = True
        self.canvas.delete("all")
        self.zakazi(PAUZA_PRIJE_PRVOG_STIMULUSA_MS, self._prikazi_prvi_stimulus)

    def _prikazi_prvi_stimulus(self):
        self.prikazi_stimulus(
            self.trenutne_brzine[0],
            broj_stimulusa=1,
            po_zavrsetku=self.pauza_prije_drugog_stimulusa,
        )

    def pauza_prije_drugog_stimulusa(self):
        self.canvas.delete("all")
        self.canvas.create_text(
            380,
            190,
            text="+",
            font=(FONT_PORODICA, 28),
            fill=BOJA_TEKST_MEKI,
        )
        self.zakazi(
            PAUZA_IZMEDJU_STIMULUSA_MS,
            lambda: self.prikazi_stimulus(
                self.trenutne_brzine[1],
                broj_stimulusa=2,
                po_zavrsetku=self.omoguci_unos_odgovora,
            ),
        )

    def prikazi_stimulus(self, brzina, broj_stimulusa, po_zavrsetku):
        """Prikazuje jedno zatvaranje sake, virtuelno ili na stvarnoj protezi."""
        if self.nacin_ispitivanja == NACIN_STVARNO:
            self._prikazi_stimulus_stvarno(brzina, broj_stimulusa, po_zavrsetku)
        else:
            self._prikazi_stimulus_virtuelno(brzina, broj_stimulusa, po_zavrsetku)

    @staticmethod
    def _izracunaj_trajanje_ms(brzina, faktor=FAKTOR_TRAJANJA_ZATVARANJA):
        ukupno_pomjeranje = 115.0
        maksimalna_brzina_piksela = 180.0
        brzina_piksela = maksimalna_brzina_piksela * brzina / 100.0
        return int(
            1000 * ukupno_pomjeranje / brzina_piksela * faktor
        )

    def _prikazi_stimulus_virtuelno(self, brzina, broj_stimulusa, po_zavrsetku):
        self.canvas.delete("all")
        self.canvas.create_text(
            380,
            35,
            text=f"STIMULUS {broj_stimulusa}",
            font=(FONT_PORODICA, 16, "bold"),
            fill=BOJA_AKCENT,
        )

        # Dva prsta krecu sa suprotnih strana i zatvaraju se prema sredini.
        lijevi_prst = self.canvas.create_rectangle(
            95, 135, 265, 195, fill=BOJA_PRST_A, outline=BOJA_AKCENT_TAMNA, width=2
        )
        desni_prst = self.canvas.create_rectangle(
            495, 215, 665, 275, fill=BOJA_PRST_B, outline="#b45309", width=2
        )
        self.canvas.create_rectangle(
            45, 115, 115, 215, fill=BOJA_PRST_A_MEKA, outline=BOJA_AKCENT_TAMNA,
            width=2,
        )
        self.canvas.create_rectangle(
            645, 195, 715, 295, fill=BOJA_PRST_B_MEKA, outline="#b45309", width=2
        )
        self.canvas.create_text(
            380,
            335,
            text="Posmatrajte brzinu zatvaranja",
            font=(FONT_PORODICA, 11),
            fill=BOJA_TEKST_MEKI,
        )

        ukupno_pomjeranje = 115.0
        trajanje = (
            self._izracunaj_trajanje_ms(brzina, FAKTOR_TRAJANJA_VIRTUELNO) / 1000.0
        )
        pocetak = time.perf_counter()
        prethodni_pomak = 0.0

        def animiraj():
            nonlocal prethodni_pomak
            proteklo = time.perf_counter() - pocetak
            napredak = min(proteklo / trajanje, 1.0)
            ukupni_pomak = ukupno_pomjeranje * napredak
            korak = ukupni_pomak - prethodni_pomak
            prethodni_pomak = ukupni_pomak

            self.canvas.move(lijevi_prst, korak, 0)
            self.canvas.move(desni_prst, -korak, 0)

            if napredak < 1.0:
                self.zakazi(BRZINA_OSVJEZAVANJA_MS, animiraj)
            else:
                self.zakazi(400, po_zavrsetku)

        self.zakazi(350, animiraj)

    def _prikazi_stimulus_stvarno(self, brzina, broj_stimulusa, po_zavrsetku):
        """Ne prikazuje animaciju — ispitanik posmatra stvarnu protezu."""
        self.canvas.delete("all")
        self.canvas.create_text(
            380,
            160,
            text=f"STIMULUS {broj_stimulusa}",
            font=(FONT_PORODICA, 16, "bold"),
            fill=BOJA_AKCENT,
        )
        self.canvas.create_text(
            380,
            200,
            text="Posmatrajte brzinu zatvaranja proteze",
            font=(FONT_PORODICA, 12),
            fill=BOJA_TEKST_MEKI,
        )

        trajanje_ms = self._izracunaj_trajanje_ms(brzina)

        def zavrsi_pokret():
            self.proteza.otvori_saku(BRZINA_OTVARANJA)
            self.zakazi(400, po_zavrsetku)

        self.zakazi(350, lambda: self.proteza.zatvori_saku(brzina))
        self.zakazi(350 + trajanje_ms, zavrsi_pokret)

    def omoguci_unos_odgovora(self):
        self.canvas.delete("all")
        self.canvas.create_text(
            380,
            165,
            text="Koje zatvaranje je bilo brze?",
            font=(FONT_PORODICA, 21, "bold"),
            fill=BOJA_TEKST,
        )
        self.canvas.create_text(
            380,
            215,
            text="Izaberite PRVO ili DRUGO",
            font=(FONT_PORODICA, 13),
            fill=BOJA_TEKST_MEKI,
        )
        self.animacija_u_toku = False
        self.vrijeme_pocetka_odgovora = time.perf_counter()
        self.omoguci_odgovore(True)

    def omoguci_odgovore(self, omoguceno):
        stanje = "normal" if omoguceno else "disabled"
        if hasattr(self, "dugme_prvo"):
            self.dugme_prvo.config(state=stanje)
            self.dugme_drugo.config(state=stanje)

    def zabiljezi_odgovor(self, odgovor):
        if self.animacija_u_toku or self.vrijeme_pocetka_odgovora is None:
            return
        if str(self.dugme_prvo.cget("state")) == "disabled":
            return

        self.omoguci_odgovore(False)
        vrijeme_odgovora = time.perf_counter() - self.vrijeme_pocetka_odgovora
        self.vrijeme_pocetka_odgovora = None
        tacan = odgovor == self.tacan_odgovor

        if self.faza == "probna":
            self.sacuvaj_red(
                odgovor=odgovor,
                tacan=tacan,
                vrijeme_odgovora=vrijeme_odgovora,
                rezultat_koraka=None,
            )
            boja = BOJA_USPEH if tacan else BOJA_GRESKA
            tekst = "TACNO" if tacan else (
                f"NETACNO — tacan odgovor je bio {self.tacan_odgovor}."
            )
            self.canvas.delete("all")
            self.canvas.create_text(
                380,
                190,
                text=tekst,
                font=(FONT_PORODICA, 20, "bold"),
                fill=boja,
            )
            self.zakazi(
                PAUZA_POSLIJE_ODGOVORA_MS,
                self.sljedeci_probni_pokusaj,
            )
            return

        rezultat = self.stepenasti.obradi_odgovor(tacan)
        self.sacuvaj_red(
            odgovor=odgovor,
            tacan=tacan,
            vrijeme_odgovora=vrijeme_odgovora,
            rezultat_koraka=rezultat,
        )
        self.canvas.delete("all")
        self.canvas.create_text(
            380,
            190,
            text="Odgovor je zabelezen.",
            font=(FONT_PORODICA, 16),
            fill=BOJA_TEKST_MEKI,
        )
        self.zakazi(
            PAUZA_POSLIJE_ODGOVORA_MS,
            self.sljedeci_glavni_pokusaj,
        )

    def prekini_ispitivanje(self):
        potvrda = messagebox.askyesno(
            "Prekid ispitivanja",
            "Da li sigurno zelite prekinuti ispitivanje i prikazati "
            "dosadasnje rezultate?",
        )
        if not potvrda:
            return

        self.ispitivanje_prekinuto = True
        self.animacija_u_toku = False
        self.vrijeme_pocetka_odgovora = None
        self.omoguci_odgovore(False)
        self.otkazi_zakazane_poslove()
        self.proteza.zaustavi()

        if self.stepenasti is not None:
            self.stepenasti.zavrsen = True
            self.stepenasti.razlog_zavrsetka = "Ispitivanje je rucno prekinuto."

        self.zavrsi_test(prekinut=True)

    # ------------------------------------------------------------------
    # CUVANJE PODATAKA
    # ------------------------------------------------------------------

    def pripremi_csv_datoteku(self):
        bezbjedno_ime = re.sub(
            r"[^A-Za-z0-9_-]+",
            "_",
            self.podaci_ispitanika["ime_ispitanika"],
        ).strip("_") or "ispitanik"
        vrijeme = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        folder = Path(__file__).resolve().parent / "rezultati"
        folder.mkdir(exist_ok=True)
        self.putanja_csv = folder / f"{bezbjedno_ime}_{vrijeme}.csv"

    def sacuvaj_red(
        self,
        odgovor,
        tacan,
        vrijeme_odgovora,
        rezultat_koraka,
    ):
        broj_pokusaja = (
            self.broj_probnog_pokusaja
            if self.faza == "probna"
            else self.broj_pokusaja
        )
        razlika = abs(self.trenutne_brzine[0] - self.trenutne_brzine[1])

        red = {
            **self.podaci_ispitanika,
            "datum_i_vrijeme": datetime.now().isoformat(timespec="seconds"),
            "faza": self.faza,
            "pokusaj": broj_pokusaja,
            "brzina_stimulusa_1": self.trenutne_brzine[0],
            "brzina_stimulusa_2": self.trenutne_brzine[1],
            "standardna_brzina": STANDARDNA_BRZINA,
            "uporedna_brzina": max(self.trenutne_brzine),
            "razlika_prije_odgovora": razlika,
            "tacan_odgovor": self.tacan_odgovor,
            "odgovor_ispitanika": odgovor,
            "odgovor_tacan": int(tacan),
            "vrijeme_odgovora_s": round(vrijeme_odgovora, 3),
            "smjer_nakon_odgovora": (
                rezultat_koraka.smjer if rezultat_koraka else ""
            ),
            "razlika_nakon_odgovora": (
                rezultat_koraka.razlika_poslije if rezultat_koraka else razlika
            ),
            "promjena_smjera": (
                int(rezultat_koraka.promjena_smjera)
                if rezultat_koraka
                else 0
            ),
            "ukupno_promjena_smjera": (
                rezultat_koraka.broj_promjena_smjera
                if rezultat_koraka
                else 0
            ),
            "status_testa": "u_toku",
        }
        self.redovi_za_csv.append(red)
        self.upisi_csv()

    def upisi_csv(self):
        if not self.redovi_za_csv or self.putanja_csv is None:
            return
        with self.putanja_csv.open("w", newline="", encoding="utf-8-sig") as fajl:
            pisac = csv.DictWriter(fajl, fieldnames=self.redovi_za_csv[0].keys())
            pisac.writeheader()
            pisac.writerows(self.redovi_za_csv)

    # ------------------------------------------------------------------
    # ZAVRSNI EKRAN
    # ------------------------------------------------------------------

    def nacrtaj_grafikon_rezultata(self, jnd=None):
        senka, karta = self.napravi_karticu(self.glavni_okvir, popuna=16)
        senka.pack(pady=6)
        tk.Label(
            karta,
            text="Tok adaptivnog postupka",
            bg=BOJA_KARTICA,
            fg=BOJA_TEKST,
            font=(FONT_PORODICA, 12, "bold"),
        ).pack(anchor="w", pady=(0, 8))

        sirina = 850
        visina = 250
        grafikon = tk.Canvas(
            karta,
            width=sirina,
            height=visina,
            bg=BOJA_KARTICA,
            highlightthickness=0,
        )
        grafikon.pack()

        glavni_redovi = [
            red for red in self.redovi_za_csv if red["faza"] == "glavna"
        ]
        if not glavni_redovi:
            grafikon.create_text(
                sirina / 2,
                visina / 2,
                text="Nema zavrsenih pokusaja u glavnom testu.",
                font=(FONT_PORODICA, 13),
                fill=BOJA_TEKST_MEKI,
            )
            return

        vrijednosti = [
            float(red["razlika_prije_odgovora"]) for red in glavni_redovi
        ]
        lijevo, desno = 62, sirina - 25
        gore, dole = 28, visina - 43
        sirina_crteza = desno - lijevo
        visina_crteza = dole - gore

        vrijednosti_za_opseg = list(vrijednosti)
        if jnd is not None:
            vrijednosti_za_opseg.append(float(jnd))
        maksimum = max(vrijednosti_za_opseg) + 2
        maksimum_y = max(5, int(math.ceil(maksimum / 5.0) * 5))

        def x_koordinata(indeks):
            if len(vrijednosti) == 1:
                return lijevo + sirina_crteza / 2
            return lijevo + indeks * sirina_crteza / (len(vrijednosti) - 1)

        def y_koordinata(vrijednost):
            return dole - (vrijednost / maksimum_y) * visina_crteza

        # Horizontalna mreza i oznake y-ose.
        for i in range(6):
            vrijednost_y = maksimum_y * i / 5
            y = y_koordinata(vrijednost_y)
            grafikon.create_line(
                lijevo,
                y,
                desno,
                y,
                fill="#e6eaf1",
                width=1,
            )
            grafikon.create_text(
                lijevo - 10,
                y,
                text=f"{vrijednost_y:.0f}",
                anchor="e",
                font=(FONT_PORODICA, 9),
                fill=BOJA_TEKST_MEKI,
            )

        grafikon.create_line(lijevo, gore, lijevo, dole, fill=BOJA_TEKST, width=2)
        grafikon.create_line(lijevo, dole, desno, dole, fill=BOJA_TEKST, width=2)

        # Brojevi pokusaja na x-osi.
        korak_oznake = max(1, math.ceil(len(vrijednosti) / 10))
        indeksi_oznaka = list(range(0, len(vrijednosti), korak_oznake))
        if len(vrijednosti) - 1 not in indeksi_oznaka:
            indeksi_oznaka.append(len(vrijednosti) - 1)
        for indeks in indeksi_oznaka:
            x = x_koordinata(indeks)
            grafikon.create_line(x, dole, x, dole + 5, fill=BOJA_TEKST)
            grafikon.create_text(
                x,
                dole + 16,
                text=str(indeks + 1),
                font=(FONT_PORODICA, 9),
                fill=BOJA_TEKST_MEKI,
            )

        tacke = []
        for indeks, vrijednost in enumerate(vrijednosti):
            tacke.extend([x_koordinata(indeks), y_koordinata(vrijednost)])
        if len(tacke) >= 4:
            grafikon.create_line(
                *tacke,
                fill=BOJA_AKCENT,
                width=2,
                smooth=False,
            )

        for indeks, (red, vrijednost) in enumerate(
            zip(glavni_redovi, vrijednosti)
        ):
            x = x_koordinata(indeks)
            y = y_koordinata(vrijednost)
            promjena_smjera = int(red["promjena_smjera"]) == 1
            boja = BOJA_GRESKA if promjena_smjera else BOJA_AKCENT
            poluprecnik = 5 if promjena_smjera else 3
            grafikon.create_oval(
                x - poluprecnik,
                y - poluprecnik,
                x + poluprecnik,
                y + poluprecnik,
                fill=boja,
                outline="white",
                width=1,
            )

        if jnd is not None:
            y_jnd = y_koordinata(jnd)
            grafikon.create_line(
                lijevo,
                y_jnd,
                desno,
                y_jnd,
                fill=BOJA_USPEH,
                width=2,
                dash=(7, 4),
            )
            grafikon.create_text(
                desno - 5,
                y_jnd - 10,
                text=f"JND = {jnd:.2f}%",
                anchor="e",
                font=(FONT_PORODICA, 9, "bold"),
                fill=BOJA_USPEH,
            )

        grafikon.create_text(
            (lijevo + desno) / 2,
            visina - 7,
            text="Broj pokusaja",
            font=(FONT_PORODICA, 10, "bold"),
            fill=BOJA_TEKST,
        )
        grafikon.create_text(
            14,
            (gore + dole) / 2,
            text="Razlika (%)",
            angle=90,
            font=(FONT_PORODICA, 10, "bold"),
            fill=BOJA_TEKST,
        )

        # legenda
        grafikon.create_line(610, 14, 635, 14, fill=BOJA_AKCENT, width=2)
        grafikon.create_text(
            640, 14, text="razlika brzina", anchor="w",
            font=(FONT_PORODICA, 8), fill=BOJA_TEKST_MEKI,
        )
        grafikon.create_oval(
            740, 9, 750, 19, fill=BOJA_GRESKA, outline="white"
        )
        grafikon.create_text(
            755, 14, text="promena smera", anchor="w",
            font=(FONT_PORODICA, 8), fill=BOJA_TEKST_MEKI,
        )

    def zavrsi_test(self, prekinut=False):
        self.otkazi_zakazane_poslove()
        self.proteza.zaustavi()

        status = "prekinut" if prekinut else "zavrsen"
        for red in self.redovi_za_csv:
            red["status_testa"] = status
        self.upisi_csv()

        zavrseni_probni = sum(
            1 for red in self.redovi_za_csv if red["faza"] == "probna"
        )
        zavrseni_glavni = sum(
            1 for red in self.redovi_za_csv if red["faza"] == "glavna"
        )
        glavni_redovi = [
            red for red in self.redovi_za_csv if red["faza"] == "glavna"
        ]
        if glavni_redovi:
            broj_tacnih = sum(int(red["odgovor_tacan"]) for red in glavni_redovi)
            tacnost = 100 * broj_tacnih / len(glavni_redovi)
            prosjecno_vrijeme = sum(
                float(red["vrijeme_odgovora_s"]) for red in glavni_redovi
            ) / len(glavni_redovi)
            statistika_odgovora = (
                f"Tacnost u glavnom testu: {tacnost:.1f}%\n"
                f"Prosecno vreme odgovora: {prosjecno_vrijeme:.2f} s\n"
            )
        else:
            statistika_odgovora = "Tacnost i vreme odgovora nisu dostupni.\n"
        broj_promjena = (
            len(self.stepenasti.promjene_smjera)
            if self.stepenasti is not None
            else 0
        )

        ima_privremeni_jnd = (
            self.stepenasti is not None
            and (
                broj_promjena > 0
                or self.stepenasti.tacnih_na_minimumu >= 7
            )
        )
        ima_konacni_jnd = not prekinut and self.stepenasti is not None

        jnd = None
        if ima_konacni_jnd or ima_privremeni_jnd:
            jnd = self.stepenasti.izracunaj_jnd()
            uporedna_na_pragu = STANDARDNA_BRZINA + jnd
            naziv_rezultata = "Privremeni JND" if prekinut else "Procenjeni JND"
            prikaz_rezultata = f"{naziv_rezultata}: {jnd:.2f}%"
            objasnjenje_jnd = (
                f"Pri standardnoj brzini od {STANDARDNA_BRZINA}% dobijena "
                f"uporedna brzina na pragu iznosi priblizno "
                f"{uporedna_na_pragu:.2f}%."
            )
            if prekinut:
                objasnjenje_jnd += (
                    " Ovo je samo privremena vrednost jer test nije "
                    "dostigao planirani broj promena smera."
                )
        else:
            naziv_rezultata = None
            prikaz_rezultata = "JND jos nije moguce izracunati"
            if self.stepenasti is not None:
                objasnjenje_jnd = (
                    "Nije zabelezena nijedna promena smera. Trenutna "
                    f"razlika izmedju brzina bila je {self.stepenasti.razlika}%."
                )
            else:
                objasnjenje_jnd = (
                    "Glavni test jos nije zapocet, pa nema dovoljno podataka "
                    "za procenu JND-a."
                )

        razlog = (
            "Ispitivanje je rucno prekinuto."
            if prekinut
            else self.stepenasti.razlog_zavrsetka
        )
        if self.putanja_csv is not None and self.putanja_csv.exists():
            podatak_o_fajlu = f"Rezultati su sacuvani u:\n{self.putanja_csv}"
        else:
            podatak_o_fajlu = (
                "CSV nije kreiran jer nije zavrsen nijedan pokusaj."
            )

        self.obrisi_sadrzaj()
        self.root.geometry("1080x880")

        ttk.Label(
            self.glavni_okvir,
            text="Test je prekinut" if prekinut else "Test je zavrsen",
            style="Naslov.TLabel",
        ).pack(pady=(10, 8))

        senka, karta_jnd = self.napravi_karticu(self.glavni_okvir, popuna=18)
        senka.pack(pady=(0, 4))
        if jnd is not None:
            tk.Label(
                karta_jnd,
                text=naziv_rezultata.upper(),
                bg=BOJA_KARTICA,
                fg=BOJA_TEKST_MEKI,
                font=(FONT_PORODICA, 10, "bold"),
            ).pack()
            tk.Label(
                karta_jnd,
                text=f"{jnd:.2f}%",
                bg=BOJA_KARTICA,
                fg=BOJA_AKCENT,
                font=(FONT_PORODICA, 40, "bold"),
            ).pack()
        else:
            tk.Label(
                karta_jnd,
                text=prikaz_rezultata,
                bg=BOJA_KARTICA,
                fg=BOJA_TEKST,
                font=(FONT_PORODICA, 16, "bold"),
            ).pack()

        self.nacrtaj_grafikon_rezultata(jnd=jnd)

        tekst = (
            f"{objasnjenje_jnd}\n\n"
            f"Zavrseni probni pokusaji: {zavrseni_probni}\n"
            f"Zavrseni pokusaji u glavnom testu: {zavrseni_glavni}\n"
            f"{statistika_odgovora}"
            f"Broj promena smera: {broj_promjena}\n"
            f"Razlog zavrsetka: {razlog}\n\n"
            f"{podatak_o_fajlu}"
        )
        senka, karta_info = self.napravi_karticu(self.glavni_okvir, popuna=18)
        senka.pack(pady=6)
        tk.Label(
            karta_info,
            text=tekst,
            bg=BOJA_KARTICA,
            fg=BOJA_TEKST,
            font=(FONT_PORODICA, 10),
            justify="left",
            wraplength=860,
        ).pack(anchor="w")

        ttk.Button(
            self.glavni_okvir,
            text="ZATVORI APLIKACIJU",
            style="Primarno.TButton",
            command=self.root.destroy,
        ).pack(pady=10)


if __name__ == "__main__":
    glavni_prozor = tk.Tk()
    aplikacija = Aplikacija(glavni_prozor)
    glavni_prozor.mainloop()
