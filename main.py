import os
import json
import logging
import asyncio
from datetime import datetime
from dotenv import load_dotenv
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes
from web3 import Web3
import requests
from clanker import ClankerSniper

# Configuration du logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Chargement des variables d'environnement
load_dotenv()

# Configuration
TELEGRAM_TOKEN = os.getenv('TELEGRAM_TOKEN')
PRIVATE_KEY = os.getenv('PRIVATE_KEY')
QUICKNODE_RPC = "https://damp-necessary-frog.base-mainnet.quiknode.pro/d60be1af9ee2c8dade56c2372d1b4b166205e14e/"
CLANKER_API = "https://api.clanker.xyz"

# Initialisation Web3
w3 = Web3(Web3.HTTPProvider(QUICKNODE_RPC))

# Initialisation du sniper
sniper = ClankerSniper(QUICKNODE_RPC, PRIVATE_KEY)

# Structure pour stocker les snipe en attente
active_snipes = {}

async def notify_user(context, user_id, message):
    """Envoie une notification à l'utilisateur"""
    try:
        await context.bot.send_message(chat_id=user_id, text=message)
    except Exception as e:
        logger.error(f"Erreur lors de l'envoi de la notification: {str(e)}")

async def handle_new_token(token, context):
    """Gère la découverte d'un nouveau token"""
    fid = token.get('fid')
    if fid in active_snipes:
        snipe_data = active_snipes[fid]
        user_id = snipe_data['user_id']
        amount = snipe_data['amount']

        # Notification de découverte
        await notify_user(context, user_id, 
            f"🎯 Nouveau token détecté!\n"
            f"Nom: {token.get('name')}\n"
            f"Contract: {token.get('address')}\n"
            f"FID: {fid}\n"
            f"Tentative d'achat de {amount} WETH..."
        )

        try:
            # Conversion du montant en Wei
            amount_wei = Web3.to_wei(amount, 'ether')
            
            # Approbation WETH
            approve_tx = sniper.approve_weth(amount_wei)
            if not approve_tx:
                raise Exception("Échec de l'approbation WETH")

            # Exécution du swap avec gas price élevé
            gas_price = Web3.to_wei(0.1, 'gwei')  # Gas price élevé pour priorité
            swap_tx = sniper.execute_swap(token['address'], amount_wei, gas_price)
            
            if swap_tx and swap_tx['status'] == 1:
                await notify_user(context, user_id,
                    f"✅ Achat réussi!\n"
                    f"Transaction: https://basescan.org/tx/{swap_tx['transactionHash'].hex()}"
                )
            else:
                raise Exception("Échec de la transaction")

        except Exception as e:
            await notify_user(context, user_id,
                f"❌ Erreur lors de l'achat: {str(e)}"
            )

async def monitor_tokens_task(context: ContextTypes.DEFAULT_TYPE):
    """Tâche de fond pour monitorer les nouveaux tokens"""
    while True:
        for fid in list(active_snipes.keys()):
            try:
                tokens = sniper.get_clanker_tokens(fid)
                if tokens:
                    for token in tokens:
                        await handle_new_token(token, context)
            except Exception as e:
                logger.error(f"Erreur lors du monitoring du FID {fid}: {str(e)}")
        
        await asyncio.sleep(5)  # Attente de 5 secondes entre chaque vérification

# Commandes du bot
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Commande /start"""
    await update.message.reply_text(
        "Bienvenue sur ClankerSniper Bot! Utilisez /help pour voir les commandes disponibles."
    )

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Commande /help"""
    help_text = """
Commandes disponibles:

/snipe <FID> <montant_WETH> - Configure un snipe pour un FID spécifique
/list - Affiche la liste des snipe actifs
/remove <FID> - Supprime un snipe actif
/update <FID> <nouveau_montant> - Met à jour le montant d'un snipe
/help - Affiche ce message d'aide
    """
    await update.message.reply_text(help_text)

async def snipe(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Commande /snipe"""
    try:
        if len(context.args) != 2:
            await update.message.reply_text("Usage: /snipe <FID> <montant_WETH>")
            return

        fid = context.args[0]
        amount = float(context.args[1])

        if amount <= 0:
            await update.message.reply_text("Le montant doit être supérieur à 0")
            return

        active_snipes[fid] = {
            'amount': amount,
            'user_id': update.effective_user.id,
            'timestamp': datetime.now().isoformat()
        }

        await update.message.reply_text(
            f"Snipe configuré pour le FID {fid} avec {amount} WETH"
        )

    except ValueError:
        await update.message.reply_text("Format invalide. Usage: /snipe <FID> <montant_WETH>")

async def list_snipes(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Commande /list"""
    if not active_snipes:
        await update.message.reply_text("Aucun snipe actif")
        return

    message = "Snipe actifs:\n\n"
    for fid, data in active_snipes.items():
        message += f"FID: {fid}\n"
        message += f"Montant: {data['amount']} WETH\n"
        message += f"Configuré le: {data['timestamp']}\n\n"

    await update.message.reply_text(message)

async def remove_snipe(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Commande /remove"""
    if not context.args or len(context.args) != 1:
        await update.message.reply_text("Usage: /remove <FID>")
        return

    fid = context.args[0]
    if fid in active_snipes:
        del active_snipes[fid]
        await update.message.reply_text(f"Snipe pour le FID {fid} supprimé")
    else:
        await update.message.reply_text(f"Aucun snipe trouvé pour le FID {fid}")

async def update_snipe(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Commande /update"""
    if len(context.args) != 2:
        await update.message.reply_text("Usage: /update <FID> <nouveau_montant>")
        return

    try:
        fid = context.args[0]
        new_amount = float(context.args[1])

        if new_amount <= 0:
            await update.message.reply_text("Le montant doit être supérieur à 0")
            return

        if fid in active_snipes:
            active_snipes[fid]['amount'] = new_amount
            await update.message.reply_text(f"Montant mis à jour pour le FID {fid}: {new_amount} WETH")
        else:
            await update.message.reply_text(f"Aucun snipe trouvé pour le FID {fid}")

    except ValueError:
        await update.message.reply_text("Format invalide. Usage: /update <FID> <nouveau_montant>")

async def main():
    """Fonction principale"""
    application = Application.builder().token(TELEGRAM_TOKEN).build()

    # Ajout des handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("snipe", snipe))
    application.add_handler(CommandHandler("list", list_snipes))
    application.add_handler(CommandHandler("remove", remove_snipe))
    application.add_handler(CommandHandler("update", update_snipe))

    # Démarrage du monitoring en arrière-plan
    asyncio.create_task(monitor_tokens_task(application))

    # Démarrage du bot
    await application.run_polling()

if __name__ == '__main__':
    asyncio.run(main()) 