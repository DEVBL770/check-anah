import time
import smtplib
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from webdriver_manager.chrome import ChromeDriverManager
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.base import MIMEBase
from email import encoders
import os
import json

# --- CONFIGURATION via les variables d'environnement (plus sécurisé) ---
EMAIL_DESTINATAIRE = os.getenv("EMAIL_DESTINATAIRE")
EMAIL_ENVOYEUR = os.getenv("EMAIL_ENVOYEUR")
MDP_ENVOYEUR = os.getenv("MDP_ENVOYEUR")
ANAH_LOGIN = os.getenv("ANAH_LOGIN")
ANAH_MDP = os.getenv("ANAH_MDP")

# Fichier pour sauvegarder l'état précédent
STATE_FILE = "anah_status.json"

def envoi_mail(message, chemin_capture=None):
    if not all([EMAIL_DESTINATAIRE, EMAIL_ENVOYEUR, MDP_ENVOYEUR]):
        print("Variables d'environnement pour l'email non configurées. Annulation de l'envoi.")
        return
    try:
        print(f"Tentative d'envoi mail à {EMAIL_DESTINATAIRE} depuis {EMAIL_ENVOYEUR}")
        msg = MIMEMultipart()
        msg['From'] = EMAIL_ENVOYEUR
        msg['To'] = EMAIL_DESTINATAIRE
        msg['Subject'] = "Changement statut dossier ANAH"
        msg.attach(MIMEText(f"{message}", "plain", "utf-8"))

        if chemin_capture and os.path.exists(chemin_capture):
            part = MIMEBase('application', 'octet-stream')
            with open(chemin_capture, "rb") as file:
                part.set_payload(file.read())
            encoders.encode_base64(part)
            part.add_header('Content-Disposition', f'attachment; filename="{os.path.basename(chemin_capture)}"')
            msg.attach(part)

        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as serveur:
            serveur.login(EMAIL_ENVOYEUR, MDP_ENVOYEUR)
            serveur.sendmail(EMAIL_ENVOYEUR, EMAIL_DESTINATAIRE, msg.as_string())
        print("Mail envoyé avec succès.")
    except Exception as e:
        print(f"Erreur envoi mail: {e}")

def get_statuts():
    # Options pour faire fonctionner Chrome dans un environnement sans écran (comme GitHub Actions)
    chrome_options = Options()
    chrome_options.add_argument("--headless")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("--window-size=1920,1080")

    driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=chrome_options)
    wait = WebDriverWait(driver, 20)
    
    try:
        driver.get("https://monprojet.anah.gouv.fr/users/sign_in")
        print("Page login ouverte")

        # Gérer le popup cookies
        try:
            cookie_btn = wait.until(EC.element_to_be_clickable((By.XPATH, "//button[normalize-space(text())='Tout accepter']")))
            cookie_btn.click()
            print("Cookie 'Tout accepter' cliqué")
            time.sleep(1)
        except Exception as e:
            print(f"Pas de pop-up cookie ou erreur : {e}")

        # Cliquer sur "J'ai été désigné mandataire"
        bouton_mandataire = wait.until(EC.element_to_be_clickable((By.XPATH, "//button[contains(., \"J'ai été désigné mandataire\")]")))
        bouton_mandataire.click()
        print("Onglet 'mandataire' cliqué")

        # Remplir l'identifiant et le mot de passe
        wait.until(EC.visibility_of_element_located((By.ID, "mandatory_email"))).send_keys(ANAH_LOGIN)
        champ_mdp = wait.until(EC.visibility_of_element_located((By.ID, "mandatory_password")))
        champ_mdp.send_keys(ANAH_MDP)
        print("Champs login remplis")

        # Soumission
        champ_mdp.submit()
        print("Formulaire soumis")
        
        # Attendre la page d'accueil connectée
        wait.until(EC.presence_of_element_located((By.XPATH, "//h1[contains(text(), 'Mes projets en cours')]")))
        print("Connexion réussie, page des projets chargée.")
        
        statuts = {}
        lignes = driver.find_elements(By.CSS_SELECTOR, ".project-row")
        print(f"Nombre de lignes projet trouvées : {len(lignes)}")
        for ligne in lignes:
            try:
                nom = ligne.find_element(By.CSS_SELECTOR, ".project-title").text
                statut = ligne.find_element(By.CSS_SELECTOR, ".project-status").text
                statuts[nom] = statut
            except Exception:
                continue
        
        # Prendre une capture d'écran pour le contexte en cas de changement
        capture_file = "capture_anah.png"
        driver.save_screenshot(capture_file)
        
        return statuts, capture_file

    except Exception as e:
        print(f"Une erreur majeure est survenue pendant le scraping: {e}")
        driver.save_screenshot("error_screenshot.png") # Sauvegarde pour le débogage
        return None, None
    finally:
        driver.quit()

def charger_anciens_statuts():
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE, 'r') as f:
            return json.load(f)
    return {}

def sauvegarder_nouveaux_statuts(statuts):
    with open(STATE_FILE, 'w') as f:
        json.dump(statuts, f, indent=4)

def main():
    if not all([ANAH_LOGIN, ANAH_MDP]):
        print("Erreur: ANAH_LOGIN ou ANAH_MDP n'est pas défini dans les secrets.")
        return

    anciens_statuts = charger_anciens_statuts()
    nouveaux_statuts, capture_file = get_statuts()

    if nouveaux_statuts is None:
        print("Echec de la récupération des nouveaux statuts. Le script s'arrête.")
        return

    changements = []
    # Détecter les changements et les nouveaux dossiers
    for nom, statut in nouveaux_statuts.items():
        ancien_statut = anciens_statuts.get(nom)
        if ancien_statut is None:
            changements.append(f"NOUVEAU DOSSIER : {nom} - Statut : {statut}")
        elif ancien_statut != statut:
            changements.append(f"CHANGEMENT : {nom} - Ancien statut : {ancien_statut} -> Nouveau statut : {statut}")
    
    # Détecter les dossiers supprimés
    for nom in anciens_statuts.keys():
        if nom not in nouveaux_statuts:
            changements.append(f"DOSSIER SUPPRIMÉ : {nom}")

    if changements:
        message = "Changement(s) détecté(s) sur votre espace ANAH :\n\n" + "\n".join(changements)
        print(message)
        envoi_mail(message, chemin_capture=capture_file)
    else:
        print("Aucun changement détecté.")

    sauvegarder_nouveaux_statuts(nouveaux_statuts)
    print("Mise à jour du fichier de statuts terminée.")


if __name__ == "__main__":
    main()
