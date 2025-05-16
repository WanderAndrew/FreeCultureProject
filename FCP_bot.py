
import json
import uuid
import re
import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes, MessageHandler, filters

# Inserisci qui il tuo TOKEN
token = "inserisci qui il tuo token"

# Configura il logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Sopprimo i log INFO/DEBUG di httpx e httpcore poichè non mi servono
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)

# ordine numerico e alfabetico
def sort_key(titolo):
    match = re.match(r"(\d+)", titolo)
    if match:
        return (int(match.group(1)), titolo.lower())
    return (float('inf'), titolo.lower())


id_to_path = {}
path_to_id = {}
mail_id_to_path = {}
mail_path_to_id = {}

# Mappa: ID breve per il file archivio.json
def get_or_create_id(percorso):
    key = "::".join(percorso)
    if key in path_to_id:
        return path_to_id[key]
    new_id = str(uuid.uuid4())[:8]
    path_to_id[key] = new_id
    id_to_path[new_id] = percorso
    return new_id

# Mappa: ID breve per il file email.json
def get_or_create_mail_id(percorso):
    key = "::".join(percorso)
    if key in mail_path_to_id:
        return mail_path_to_id[key]
    new_id = str(uuid.uuid4())[:8]
    mail_path_to_id[key] = new_id
    mail_id_to_path[new_id] = percorso
    return new_id

# Carico archivio.json
with open("archivio.json", "r", encoding="utf-8") as f:
    archivio = json.load(f)

# Carico emails.json:
with open("emails.json", "r", encoding="utf-8") as f:
    rubrica = json.load(f)

# Recupero cartella da percorso
def get_folder_from_path(path, current_folder):
    for p in path:
        current_folder = current_folder["subfolders"].get(p)
        if current_folder is None:
            return None
    return current_folder

# Creazione tastiera di navigazione
ELEMENTI_PER_PAGINA = 10

def genera_keyboard(cartella_corrente, percorso_attuale, page=0):
    keyboard = []
    items = []

    # Cartelle ordinate
    nomi_cartelle_ordinate = sorted(
        cartella_corrente.get("subfolders", {}).keys(), key=sort_key
    )
    for nome_sottocartella in nomi_cartelle_ordinate:
        nuovo_percorso = percorso_attuale + [nome_sottocartella]
        short_id = get_or_create_id(nuovo_percorso)
        items.append(("cartella", nome_sottocartella, short_id))

    # File ordinati
    files = sorted(
        cartella_corrente.get("files", []), key=lambda f: sort_key(f.get("titolo", ""))
    )
    for file in files:
        items.append(("file", file.get("titolo", "File"), file.get("link", "#")))

    start = page * ELEMENTI_PER_PAGINA
    end = start + ELEMENTI_PER_PAGINA
    pagina_items = items[start:end]

    for tipo, nome, valore in pagina_items:
        if tipo == "cartella":
            keyboard.append([
                InlineKeyboardButton(
                    f"{' ' * 10} 📁 {nome} {' ' * 10}", callback_data=f"nav:{valore}:0"
                )
            ])
        else:
            keyboard.append([
                InlineKeyboardButton(
                    f"{' ' * 10}📄 {nome} {' ' * 10}", url=valore
                )
            ])

    # Navigazione pagine
    nav_buttons = []
    if page > 0:
        short_id = get_or_create_id(percorso_attuale)
        nav_buttons.append(
            InlineKeyboardButton("⬅️ Indietro", callback_data=f"nav:{short_id}:{page-1}")
        )
    if end < len(items):
        short_id = get_or_create_id(percorso_attuale)
        nav_buttons.append(
            InlineKeyboardButton("➡️ Successivo", callback_data=f"nav:{short_id}:{page+1}")
        )
    if nav_buttons:
        keyboard.append(nav_buttons)

    # Pulsante indietro
    if percorso_attuale:
        back_id = get_or_create_id(percorso_attuale[:-1])
        keyboard.append([
            InlineKeyboardButton("🔙 Indietro", callback_data=f"nav:{back_id}:0")
        ])

    return InlineKeyboardMarkup(keyboard)

# Ricerca nei file per titolo e tag (ordinata numericamente e alfabeticamente)
def cerca_in_cartelle(query, archivio):
    risultati = []
    query_terms = query.lower().split()

    def ricerca(cartella, percorso):
        for file in cartella.get("files", []):
            titolo = file.get("titolo", "").lower()
            tag_list = [tag.lower() for tag in file.get("tag", [])]

            if all(term in titolo or any(term in tag for tag in tag_list) for term in query_terms):
                risultati.append(file)

        for nome_sottocartella, sottocartella in cartella.get("subfolders", {}).items():
            ricerca(sottocartella, percorso + [nome_sottocartella])

    root_name = list(archivio.keys())[0]
    ricerca(archivio[root_name], [root_name])
    return sorted(risultati, key=lambda f: sort_key(f.get("titolo", "")))

# Invia risultati della ricerca con paginazione
RISULTATI_PER_PAGINA = 10 #ho impostato solo 10 risultati per pagina, potete cambiare questo numero
async def invia_risultati(update: Update, query: str, page: int = 0):
    user = update.effective_user
    logger.info(f"User {user.id} ({user.username}) ricerca '{query}' pagina {page}")
    risultati = cerca_in_cartelle(query, archivio)

    if not risultati:
        if update.message:
            await update.message.reply_text(f"🔍 Nessun risultato trovato per '{query}'.")
        else:
            await update.callback_query.edit_message_text(f"🔍 Nessun risultato trovato per '{query}'.")
        return

    start = page * RISULTATI_PER_PAGINA
    end = start + RISULTATI_PER_PAGINA
    pagina_risultati = risultati[start:end]

    keyboard = [
        [InlineKeyboardButton(f"📄 {file['titolo']}", url=file['link'])]
        for file in pagina_risultati
    ]

    nav_buttons = []
    if page > 0:
        nav_buttons.append(InlineKeyboardButton("⬅️ Indietro", callback_data=f"search:{query}:{page-1}"))
    if end < len(risultati):
        nav_buttons.append(InlineKeyboardButton("➡️ Successivo", callback_data=f"search:{query}:{page+1}"))
    if nav_buttons:
        keyboard.append(nav_buttons)

    if update.message:
        await update.message.reply_text(
            f"🔍 Risultati per '{query}' (pagina {page+1}):",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
    else:
        await update.callback_query.edit_message_text(
            f"🔍 Risultati per '{query}' (pagina {page+1}):",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

# /cerca handler
async def cerca(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    logger.info(f"User {user.id} ({user.username}) ha usato /cerca")
    query = ' '.join(context.args)
    if query:
        await invia_risultati(update, query, page=0)
    else:
        await update.message.reply_text("⚠️ Inserisci una query. Esempio: /cerca algebra")

# /start handler
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    logger.info(f"User {user.id} ({user.username}) ha avviato il bot con /start")
    keyboard = genera_keyboard(archivio[list(archivio.keys())[0]], [])
    await update.message.reply_text(
        f"📚 *{list(archivio.keys())[0]}*", reply_markup=keyboard, parse_mode="Markdown"
    )

# Callback per navigazione tra cartelle o paginazione ricerca
async def naviga(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query_cb = update.callback_query
    user = query_cb.from_user
    data = query_cb.data
    logger.info(f"User {user.id} ({user.username}) ha cliccato button: {data}")
    await query_cb.answer()
    
    if data.startswith("search:"):
        _, q, p = data.split(":", 2)
        await invia_risultati(update, q, int(p))
        return
    
    if data.startswith("nav:"):
        _, short_id, page_str = data.split(":", 2)
        page = int(page_str)
        path_list = id_to_path.get(short_id)
    else:
        short_id = data
        page = 0
        path_list = id_to_path.get(short_id)

    if path_list is None:
        await query_cb.edit_message_text("❌ Cartella non trovata o ID non valido.")
        return

    folder = get_folder_from_path(path_list, archivio[list(archivio.keys())[0]])
    if folder is None:
        await query_cb.edit_message_text("❌ Cartella non trovata.")
        return

    keyboard = genera_keyboard(folder, path_list, page=page)
    title = path_list[-1] if path_list else list(archivio.keys())[0]
    await query_cb.edit_message_text(
        f"📂 *{title}*", reply_markup=keyboard, parse_mode="Markdown"
    )

# Comando sconosciuto
async def comando_sconosciuto(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    logger.info(f"User {user.id} ({user.username}) ha inviato comando sconosciuto: {update.message.text}")
    await update.message.reply_text("❌ Comando non riconosciuto. Usa /help per sapere come usare questo bot!")

# Comando /help
async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    logger.info(f"User {user.id} ({user.username}) ha usato /help")
    messaggio = (
        "📖 *Come usare questo bot:*\n\n"
        "🔹 Usa /start per esplorare la libreria digitale tramite pulsanti.\n\n"
        "🔹 Usa /cerca seguito da una o più parole chiave per cercare tra i file. Es.:\n"
        "`/cerca chimica esami svolti`\n\n"
        "🔹 La ricerca considera titoli e tag dei file.\n\n"
        "🔹 Clicca sui pulsanti 📁 per entrare nelle cartelle, e su 📄 per aprire un file.\n\n"
        "🔹 I risultati della ricerca sono paginati se troppi, ti basterà cliccare\n ➡️ Successivo.\n\n"
        "🔹 Usa /upload per sapere come inviarci i file!\n\n"
        "🔹 Usa /libri per trovare libri in PDF.\n\n"
        "🔹 Usa /mail per sfogliare tutta la rubrica delle mail dei prof.\n\n"
        "❓ *Hai domande o problemi?* \n"
        "[➡️ Scrivici, ti risponderemo subito!](https://t.me/FreeCultureProject)\n\n\n"
        "ℹ️ _Questo bot è parte del progetto FreeCultureProject._\n"
        "🌐 https://www.freecultureproject.com"
    )
    await update.message.reply_text(messaggio, parse_mode="Markdown")

# 📤 Comando /upload
async def upload_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    logger.info(f"User {user.id} ({user.username}) ha usato /upload")
    messaggio = (
        "📤 *Come contribuire alla libreria:*\n\n"
        "Puoi inviarmi nuovi file direttamente in *chat privata*!\n\n"
        "[➡️ Clicca qui per aprire la chat privata](https://t.me/FreeCultureProject)\n\n"
        "📌 Una volta inviato il file, verrà valutato e aggiunto alla libreria.\n\n"
        "Grazie per il tuo contributo! ✨"
    )
    await update.message.reply_text(messaggio, parse_mode="Markdown", disable_web_page_preview=True)

# 📚 Comando /libri
async def libri_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    logger.info(f"User {user.id} ({user.username}) ha usato /libri")
    messaggio = (
        "📚 *Cerchi libri in PDF?*\n\n"
        "Date un'occhiata qua!\n"
        "[➡️ Clicca qui per accedere ai libri](https://z-library.sk)\n\n"
        "Il link è verificato e sicuro 📖✨"
    )
    await update.message.reply_text(messaggio, parse_mode="Markdown", disable_web_page_preview=True)


# INIZIO COMANDO MAIL E MENU INLINE PER LE MAIL ----------------------

# --- Comando /mail: presenta la lista degli anni
async def mail_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    logger.info(f"User {user.id} ({user.username}) ha usato /mail")
    # Inline buttons con le chiavi di primo livello (gli anni)
    keyboard = []
    for anno in rubrica.keys():
        mid1 = get_or_create_mail_id([anno])
        keyboard.append([
            InlineKeyboardButton(
                anno,
                callback_data=f"mail:{mid1}"
            )
        ])
    await update.message.reply_text(
        "📧 *Rubrica email docenti*\n\nSeleziona l'anno di corso:",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

# --- Callback per navigare nel menu /mail
async def mail_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    parts = query.data.split(":")

    # TORNA AGLI ANNI
    if parts[1] == "back":
        keyboard = []
        for anno in rubrica.keys():
            mid1 = get_or_create_mail_id([anno])
            keyboard.append([
                InlineKeyboardButton(
                    anno,
                    callback_data=f"mail:{mid1}"
                )
            ])
        return await query.edit_message_text(
            "📧 *Rubrica email docenti*\n\nSeleziona l'anno di corso:",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

    # HO CLICCATO SU UN ANNO (mail:<mid1>)
    if len(parts) == 2:
        mid1 = parts[1]
        percorso1 = mail_id_to_path.get(mid1)
        if not percorso1:
            return await query.edit_message_text("❌ Anno non valido.")
        anno = percorso1[0]

        # elenco materie con doppio livello di callback
        keyboard = []
        for mat in rubrica[anno].keys():
            mid2 = get_or_create_mail_id([anno, mat])
            keyboard.append([
                InlineKeyboardButton(
                    mat,
                    callback_data=f"mail:{mid1}:{mid2}"
                )
            ])
        # pulsante back anni
        keyboard.append([
            InlineKeyboardButton("🔙 Anni", callback_data="mail:back")
        ])
        return await query.edit_message_text(
            f"📧 *Rubrica* — _{anno}_\n\nSeleziona la materia:",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

    # HO CLICCATO SU UNA MATERIA (mail:<mid1>:<mid2>)
    if len(parts) == 3:
        mid2 = parts[2]
        percorso2 = mail_id_to_path.get(mid2)
        if not percorso2 or len(percorso2) != 2:
            return await query.edit_message_text("❌ Materia non valida.")
        anno, materia = percorso2
        profs = rubrica[anno].get(materia, {})

        text = f"📧 *Rubrica* — _{anno} → {materia}_\n\n"
        text += "\n".join(f"• *{n}*: `{e}`" for n, e in profs.items())

        # pulsanti per tornare a materie o anni
        mid1 = get_or_create_mail_id([anno])
        keyboard = [[
            InlineKeyboardButton("🔙 Materie", callback_data=f"mail:{mid1}"),
            InlineKeyboardButton("🏠 Anni",    callback_data="mail:back")
        ]]
        return await query.edit_message_text(
            text,
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

# FINE COMANDO MAIL E MENU INLINE PER LE MAIL ----------------------


# 🚀 Avvio del bot
def main():
    app = Application.builder().token(token).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("cerca", cerca))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("upload", upload_command))
    app.add_handler(CommandHandler("libri", libri_command))
    app.add_handler(CommandHandler("mail", mail_command))
    app.add_handler(CallbackQueryHandler(mail_callback, pattern=r"^mail:"))
    app.add_handler(CallbackQueryHandler(naviga, pattern=r"^(?!mail:).*"))
    # ⛔ Catch-all per comandi non riconosciuti
    app.add_handler(MessageHandler(filters.COMMAND, comando_sconosciuto))

    print("✅ Bot avviato")
    app.run_polling()

if __name__ == "__main__":
    main()
