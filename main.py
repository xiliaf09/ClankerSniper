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
UNISWAP_V3_ROUTER = "0x5615CDAb10dc425a742d643d949a7F474C01abc4"  # Uniswap v3 router on Base
WETH_ADDRESS = "0x4200000000000000000000000000000000000006"  # WETH on Base
slippage = 100  # Slippage en %, 100% par défaut (minOut=0)

# Initialisation Web3
w3 = Web3(Web3.HTTPProvider(QUICKNODE_RPC))

# Initialisation du sniper
sniper = ClankerSniper(QUICKNODE_RPC, PRIVATE_KEY)

# Structure pour stocker les snipe en attente
active_snipes = {}

# Nouvelle structure pour suivre les tokens déjà alertés
alerted_tokens = set()

# Liste des utilisateurs abonnés aux alertes (ayant fait /start)
subscribed_users = set()

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
    logger.info("Démarrage du monitoring des tokens...")
    while True:
        try:
            for fid in list(active_snipes.keys()):
                try:
                    tokens = sniper.get_clanker_tokens(fid)
                    if tokens:
                        for token in tokens:
                            await handle_new_token(token, context)
                except Exception as e:
                    logger.error(f"Erreur lors du monitoring du FID {fid}: {str(e)}")
            
            await asyncio.sleep(5)  # Attente de 5 secondes entre chaque vérification
        except Exception as e:
            logger.error(f"Erreur dans la boucle de monitoring: {str(e)}")
            await asyncio.sleep(5)

async def monitor_new_tokens_task(context: ContextTypes.DEFAULT_TYPE):
    """Tâche de fond pour monitorer les nouveaux tokens déployés sur Clanker"""
    logger.info("Démarrage du monitoring global des nouveaux tokens...")
    while True:
        try:
            response = requests.get("https://www.clanker.world/api/tokens")
            if response.status_code == 200:
                tokens = response.json().get("data", [])
                if tokens:
                    token = tokens[0]  # Le plus récent
                    token_id = token.get('contract_address')
                    if token_id and token_id not in alerted_tokens:
                        alerted_tokens.add(token_id)
                        nom = token.get('name', 'N/A')
                        ticker = token.get('symbol', 'N/A')
                        fid = token.get('requestor_fid', 'N/A')
                        contract = token.get('contract_address', 'N/A')
                        pool = token.get('pool_address', 'N/A')
                        message = (
                            f"🚨 Nouveau token déployé !\n"
                            f"Nom : {nom}\n"
                            f"Ticker : {ticker}\n"
                            f"FID : {fid}\n"
                            f"Contract : {contract}\n"
                            f"Pool : {pool}"
                        )
                        # Envoyer l'alerte à tous les abonnés
                        for user_id in subscribed_users:
                            await notify_user(context, user_id, message)
            else:
                logger.error(f"Erreur lors de la récupération des nouveaux tokens : {response.status_code}")
        except Exception as e:
            logger.error(f"Erreur dans la boucle de monitoring global : {str(e)}")
        await asyncio.sleep(1)

# Commandes du bot
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Commande /start"""
    logger.info(f"Commande /start reçue de l'utilisateur {update.effective_user.id}")
    try:
        # Ajouter l'utilisateur à la liste des abonnés
        subscribed_users.add(update.effective_user.id)
        await update.message.reply_text(
            "Bienvenue sur ClankerSniper Bot! Utilisez /help pour voir les commandes disponibles.\n\nVous recevrez désormais une alerte à chaque nouveau Clanker déployé."
        )
        logger.info(f"Message de bienvenue envoyé à l'utilisateur {update.effective_user.id}")
    except Exception as e:
        logger.error(f"Erreur lors de l'envoi du message de bienvenue: {str(e)}")

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Commande /help"""
    logger.info(f"Commande /help reçue de l'utilisateur {update.effective_user.id}")
    help_text = """
Commandes disponibles:

/snipe <FID> <montant_WETH> - Configure un snipe pour un FID spécifique
/list - Affiche la liste des snipe actifs
/remove <FID> - Supprime un snipe actif
/update <FID> <nouveau_montant> - Met à jour le montant d'un snipe
/help - Affiche ce message d'aide
    """
    try:
        await update.message.reply_text(help_text)
        logger.info(f"Message d'aide envoyé à l'utilisateur {update.effective_user.id}")
    except Exception as e:
        logger.error(f"Erreur lors de l'envoi du message d'aide: {str(e)}")

async def snipe(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Commande /snipe"""
    logger.info(f"Commande /snipe reçue de l'utilisateur {update.effective_user.id}")
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
        logger.info(f"Snipe configuré pour le FID {fid} avec {amount} WETH par l'utilisateur {update.effective_user.id}")

    except ValueError:
        await update.message.reply_text("Format invalide. Usage: /snipe <FID> <montant_WETH>")
        logger.error(f"Format invalide pour la commande /snipe de l'utilisateur {update.effective_user.id}")

async def list_snipes(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Commande /list"""
    logger.info(f"Commande /list reçue de l'utilisateur {update.effective_user.id}")
    if not active_snipes:
        await update.message.reply_text("Aucun snipe actif")
        return

    message = "Snipe actifs:\n\n"
    for fid, data in active_snipes.items():
        message += f"FID: {fid}\n"
        message += f"Montant: {data['amount']} WETH\n"
        message += f"Configuré le: {data['timestamp']}\n\n"

    try:
        await update.message.reply_text(message)
        logger.info(f"Liste des snipe envoyée à l'utilisateur {update.effective_user.id}")
    except Exception as e:
        logger.error(f"Erreur lors de l'envoi de la liste des snipe: {str(e)}")

async def remove_snipe(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Commande /remove"""
    logger.info(f"Commande /remove reçue de l'utilisateur {update.effective_user.id}")
    if not context.args or len(context.args) != 1:
        await update.message.reply_text("Usage: /remove <FID>")
        return

    fid = context.args[0]
    if fid in active_snipes:
        del active_snipes[fid]
        await update.message.reply_text(f"Snipe pour le FID {fid} supprimé")
        logger.info(f"Snipe pour le FID {fid} supprimé par l'utilisateur {update.effective_user.id}")
    else:
        await update.message.reply_text(f"Aucun snipe trouvé pour le FID {fid}")

async def update_snipe(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Commande /update"""
    logger.info(f"Commande /update reçue de l'utilisateur {update.effective_user.id}")
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
            logger.info(f"Montant mis à jour pour le FID {fid}: {new_amount} WETH par l'utilisateur {update.effective_user.id}")
        else:
            await update.message.reply_text(f"Aucun snipe trouvé pour le FID {fid}")

    except ValueError:
        await update.message.reply_text("Format invalide. Usage: /update <FID> <nouveau_montant>")
        logger.error(f"Format invalide pour la commande /update de l'utilisateur {update.effective_user.id}")

async def lastclanker(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Commande /lastclanker : affiche le dernier token Clanker déployé avec toutes les infos"""
    try:
        response = requests.get("https://www.clanker.world/api/tokens")
        if response.status_code == 200:
            tokens = response.json().get("data", [])
            if tokens:
                token = tokens[0]  # Le plus récent
                nom = token.get('name', 'N/A')
                ticker = token.get('symbol', 'N/A')
                fid = token.get('requestor_fid', 'N/A')
                contract = token.get('contract_address', 'N/A')
                pool = token.get('pool_address', 'N/A')
                message = (
                    f"🚨 Dernier Clanker déployé :\n"
                    f"Nom : {nom}\n"
                    f"Ticker : {ticker}\n"
                    f"FID : {fid}\n"
                    f"Contract : {contract}\n"
                    f"Pool : {pool}"
                )
                await update.message.reply_text(message)
            else:
                await update.message.reply_text("Aucun token Clanker trouvé récemment.")
        else:
            await update.message.reply_text(f"Erreur lors de la récupération : {response.status_code}")
    except Exception as e:
        await update.message.reply_text(f"Erreur lors de la récupération du dernier Clanker : {str(e)}")

async def slippage_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Commande /slippage <valeur> : ajuste le slippage global en pourcentage"""
    global slippage
    try:
        if len(context.args) != 1:
            await update.message.reply_text("Usage: /slippage <valeur_en_pourcentage>")
            return
        value = float(context.args[0])
        if value <= 0 or value > 100:
            await update.message.reply_text("Le slippage doit être entre 0 et 100")
            return
        slippage = value
        await update.message.reply_text(f"Slippage global réglé à {slippage}%")
    except Exception as e:
        await update.message.reply_text(f"Erreur lors du réglage du slippage : {str(e)}")

async def testswap(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Commande /testswap <token_address> <amount_weth> : effectue un swap WETH -> token sur Uniswap v3 (Base)"""
    global slippage
    try:
        if len(context.args) != 2:
            await update.message.reply_text("Usage: /testswap <token_address> <amount_weth>")
            return
        token_address = context.args[0]
        amount_weth = float(context.args[1])
        if amount_weth <= 0:
            await update.message.reply_text("Le montant doit être supérieur à 0")
            return
        amount_in_wei = Web3.to_wei(amount_weth, 'ether')
        # Estimation du minOut via le Quoter Uniswap
        try:
            min_out = sniper.get_amount_out(WETH_ADDRESS, token_address, amount_in_wei, slippage)
            if min_out == 0:
                await update.message.reply_text("⚠️ Le Quoter Uniswap retourne 0 : la pool n'existe pas, n'a pas de liquidité, ou le montant est trop faible.")
                return
        except Exception as e:
            await update.message.reply_text(f"⚠️ Erreur lors de l'estimation du minOut : {str(e)}")
            min_out = 0
        try:
            tx_hash = sniper.swap_weth_for_token(
                router_address=UNISWAP_V3_ROUTER,
                weth_address=WETH_ADDRESS,
                token_address=token_address,
                amount_in_wei=amount_in_wei,
                min_out=min_out
            )
            if tx_hash:
                await update.message.reply_text(f"✅ Swap envoyé !\nTx hash : https://basescan.org/tx/{tx_hash}")
            else:
                await update.message.reply_text("❌ Erreur lors de l'envoi du swap (aucun hash retourné)")
        except Exception as e:
            await update.message.reply_text(f"❌ Erreur détaillée lors du swap : {str(e)}")
    except Exception as e:
        await update.message.reply_text(f"Erreur de parsing : {str(e)}")

async def testswapeth(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Teste l'achat d'un token avec de l'ETH natif via Uniswap V3."""
    try:
        # Vérification des arguments
        if len(context.args) != 2:
            await update.message.reply_text(
                "❌ Format incorrect. Utilisez:\n"
                "/testswapeth <adresse_token> <montant_eth>"
            )
            return

        token_address = context.args[0]
        amount_eth = float(context.args[1])

        # Validation des entrées
        if not Web3.is_address(token_address):
            await update.message.reply_text("❌ Adresse de token invalide")
            return

        if amount_eth <= 0:
            await update.message.reply_text("❌ Le montant d'ETH doit être supérieur à 0")
            return

        # Conversion en wei
        amount_wei = Web3.to_wei(amount_eth, 'ether')

        # Message de début
        status_msg = await update.message.reply_text(
            f"🔄 Test d'achat de token avec {amount_eth} ETH...\n"
            f"Token: {token_address}\n"
            "⏳ Envoi de la transaction..."
        )

        # Exécution du swap
        tx_hash = sniper.swap_eth_for_token(token_address, amount_wei)
        
        if tx_hash and tx_hash.startswith('0x'):
            await status_msg.edit_text(
                f"✅ Transaction envoyée!\n"
                f"Hash: {tx_hash}\n"
                f"Montant: {amount_eth} ETH\n"
                f"Token: {token_address}\n"
                f"Voir sur BaseScan: https://basescan.org/tx/{tx_hash}"
            )
        else:
            await status_msg.edit_text(
                f"❌ Échec de la transaction.\nDétail: {tx_hash}"
            )

    except Exception as e:
        await update.message.reply_text(f"❌ Erreur: {str(e)}")

async def quote(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Commande /quote <token_address> <amount_weth> : affiche le minOut estimé et le montant reçu attendu pour diagnostiquer le swap"""
    global slippage
    try:
        if len(context.args) != 2:
            await update.message.reply_text("Usage: /quote <token_address> <amount_weth>")
            return
        token_address = context.args[0]
        amount_weth = float(context.args[1])
        if amount_weth <= 0:
            await update.message.reply_text("Le montant doit être supérieur à 0")
            return
        amount_in_wei = Web3.to_wei(amount_weth, 'ether')
        try:
            min_out = sniper.get_amount_out(WETH_ADDRESS, token_address, amount_in_wei, slippage)
            if min_out == 0:
                await update.message.reply_text("⚠️ Le Quoter Uniswap retourne 0 : la pool n'existe pas, n'a pas de liquidité, ou le montant est trop faible.")
                return
            amount_out = int(min_out / (1 - slippage / 100))
            await update.message.reply_text(
                f"Estimation Uniswap V3 :\n"
                f"- Montant reçu attendu (avant slippage) : {amount_out} (wei)\n"
                f"- minOut utilisé avec slippage ({slippage}%) : {min_out} (wei)\n"
                f"- minOut (en token) : {Web3.from_wei(min_out, 'ether')}"
            )
        except Exception as e:
            await update.message.reply_text(f"Erreur lors de l'estimation du minOut : {str(e)}")
    except Exception as e:
        await update.message.reply_text(f"Erreur de parsing : {str(e)}")

async def post_init(application):
    # Démarrage du monitoring global en arrière-plan une fois l'application prête
    asyncio.create_task(monitor_new_tokens_task(application))
    logger.info("Monitoring global des nouveaux tokens lancé via post_init.")

def main():
    logger.info("Démarrage du bot...")

    application = Application.builder().token(TELEGRAM_TOKEN).post_init(post_init).build()

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("snipe", snipe))
    application.add_handler(CommandHandler("list", list_snipes))
    application.add_handler(CommandHandler("remove", remove_snipe))
    application.add_handler(CommandHandler("update", update_snipe))
    application.add_handler(CommandHandler("lastclanker", lastclanker))
    application.add_handler(CommandHandler("testswap", testswap))
    application.add_handler(CommandHandler("testswapeth", testswapeth))
    application.add_handler(CommandHandler("slippage", slippage_command))
    application.add_handler(CommandHandler("quote", quote))

    logger.info("Handlers configurés, démarrage du polling...")

    # Lancement synchrone (PTB gère l'event loop)
    application.run_polling(allowed_updates=Update.ALL_TYPES, drop_pending_updates=True)

if __name__ == '__main__':
    try:
        main()
    except Exception as e:
        logger.error(f"Erreur fatale dans le bot: {str(e)}") 