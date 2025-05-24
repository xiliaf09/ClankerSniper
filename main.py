import os
import logging
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes
from dotenv import load_dotenv
from clanker import buy_token

# Configuration du logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Chargement des variables d'environnement
load_dotenv()

# Récupération du token Telegram
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
if not TELEGRAM_TOKEN:
    raise ValueError("TELEGRAM_TOKEN non trouvé dans le fichier .env")

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Gère la commande /start"""
    await update.message.reply_text(
        "👋 Bienvenue sur ClankerSniper Bot !\n\n"
        "Commandes disponibles :\n"
        "/buy <adresse_token> <montant_eth> - Acheter un token\n"
        "/help - Afficher l'aide"
    )

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Gère la commande /help"""
    await update.message.reply_text(
        "📚 Guide d'utilisation :\n\n"
        "1. Pour acheter un token :\n"
        "   /buy <adresse_token> <montant_eth>\n"
        "   Exemple : /buy 0x123... 0.1\n\n"
        "2. Assurez-vous d'avoir suffisamment d'ETH dans votre wallet\n"
        "3. Le montant doit être en ETH (pas en wei)\n"
        "4. L'adresse du token doit être valide sur Base"
    )

async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Gère les erreurs du bot"""
    error = context.error
    logger.error("Exception while handling an update:", exc_info=error)
    
    if update and update.effective_message:
        error_message = f"❌ Erreur : {str(error)}"
        if hasattr(error, 'message'):
            error_message = f"❌ Erreur : {error.message}"
        elif hasattr(error, 'args') and error.args:
            error_message = f"❌ Erreur : {error.args[0]}"
        
        # Ajout des détails supplémentaires si disponibles
        if hasattr(error, 'data'):
            error_message += f"\n\nDétails : {error.data}"
        
        await update.effective_message.reply_text(error_message)

def main():
    """Démarre le bot"""
    # Création de l'application
    application = Application.builder().token(TELEGRAM_TOKEN).build()

    # Ajout des handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("buy", buy_token))

    # Ajout du gestionnaire d'erreurs
    application.add_error_handler(error_handler)

    # Démarrage du bot avec une seule instance
    application.run_polling(allowed_updates=Update.ALL_TYPES, drop_pending_updates=True)

if __name__ == '__main__':
    main() 