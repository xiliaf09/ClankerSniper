import json
import requests
from web3 import Web3
from eth_account import Account
from web3.middleware import geth_poa_middleware
import time
import os
from telegram import Update
from telegram.ext import CallbackContext, Application, CommandHandler, ContextTypes
import threading
import asyncio
import logging
from dotenv import load_dotenv

class ClankerSniper:
    def __init__(self, rpc_url, private_key):
        self.w3 = Web3(Web3.HTTPProvider(rpc_url))
        self.w3.middleware_onion.inject(geth_poa_middleware, layer=0)
        self.account = Account.from_key(private_key)
        self.address = self.account.address

        # Adresses des contrats sur Base
        self.WETH_ADDRESS = "0x4200000000000000000000000000000000000006"
        self.UNISWAP_V3_ROUTER = "0x2626664c2603336E57B271c5C0b26F421741e481"  # Routeur officiel Uniswap V3 sur Base
        self.UNISWAP_V3_QUOTER = "0x3d4e44Eb1374240CE5F1B871ab261CD16335B76a"

        # ABI minimal pour les contrats
        self.WETH_ABI = [
            {
                "constant": False,
                "inputs": [{"name": "wad", "type": "uint256"}],
                "name": "withdraw",
                "outputs": [],
                "payable": False,
                "stateMutability": "nonpayable",
                "type": "function"
            },
            {
                "constant": False,
                "inputs": [{"name": "guy", "type": "address"}, {"name": "wad", "type": "uint256"}],
                "name": "approve",
                "outputs": [{"name": "", "type": "bool"}],
                "payable": False,
                "stateMutability": "nonpayable",
                "type": "function"
            }
        ]

        self.ROUTER_ABI = [
            {
                "inputs": [
                    {
                        "components": [
                            {"internalType": "address", "name": "tokenIn", "type": "address"},
                            {"internalType": "address", "name": "tokenOut", "type": "address"},
                            {"internalType": "uint24", "name": "fee", "type": "uint24"},
                            {"internalType": "address", "name": "recipient", "type": "address"},
                            {"internalType": "uint256", "name": "deadline", "type": "uint256"},
                            {"internalType": "uint256", "name": "amountIn", "type": "uint256"},
                            {"internalType": "uint256", "name": "amountOutMinimum", "type": "uint256"},
                            {"internalType": "uint160", "name": "sqrtPriceLimitX96", "type": "uint160"}
                        ],
                        "internalType": "struct ISwapRouter.ExactInputSingleParams",
                        "name": "params",
                        "type": "tuple"
                    }
                ],
                "name": "exactInputSingle",
                "outputs": [
                    {"internalType": "uint256", "name": "amountOut", "type": "uint256"}
                ],
                "stateMutability": "payable",
                "type": "function"
            }
        ]

        # Initialisation des contrats
        self.weth_contract = self.w3.eth.contract(address=self.WETH_ADDRESS, abi=self.WETH_ABI)
        self.router_contract = self.w3.eth.contract(address=self.UNISWAP_V3_ROUTER, abi=self.ROUTER_ABI)

    def get_clanker_tokens(self, fid=None):
        """Récupère les tokens Clanker, optionnellement filtrés par FID"""
        url = "https://api.clanker.xyz/tokens"
        if fid:
            url += f"?fid={fid}"
        
        response = requests.get(url)
        if response.status_code == 200:
            return response.json()
        return None

    def get_token_info(self, token_address):
        """Récupère les informations détaillées d'un token"""
        url = f"https://api.clanker.xyz/tokens/{token_address}"
        response = requests.get(url)
        if response.status_code == 200:
            return response.json()
        return None

    def approve_weth(self, amount):
        """Approuve le router Uniswap pour utiliser les WETH"""
        try:
            tx = self.weth_contract.functions.approve(
                self.UNISWAP_V3_ROUTER,
                amount
            ).build_transaction({
                'from': self.address,
                'gas': 100000,
                'gasPrice': self.w3.eth.gas_price,
                'nonce': self.w3.eth.get_transaction_count(self.address),
            })
            
            signed_tx = self.w3.eth.account.sign_transaction(tx, self.account.key)
            tx_hash = self.w3.eth.send_raw_transaction(signed_tx.rawTransaction)
            return self.w3.eth.wait_for_transaction_receipt(tx_hash)
        except Exception as e:
            print(f"Erreur lors de l'approbation WETH: {str(e)}")
            return None

    def execute_swap(self, token_address, amount_in, gas_price=None):
        """Exécute un swap WETH -> Token via Uniswap V3"""
        try:
            # Paramètres du swap
            params = {
                'tokenIn': self.WETH_ADDRESS,
                'tokenOut': token_address,
                'fee': 3000,  # 0.3% fee tier
                'amountIn': amount_in,
                'amountOutMinimum': 0,  # Attention: Risque de slippage
                'sqrtPriceLimitX96': 0,
                'recipient': self.address,
                'deadline': self.w3.eth.get_block('latest').timestamp + 300  # 5 minutes
            }

            # Construction de la transaction
            tx = self.router_contract.functions.exactInputSingle(params).build_transaction({
                'from': self.address,
                'gas': 300000,
                'gasPrice': gas_price or self.w3.eth.gas_price,
                'nonce': self.w3.eth.get_transaction_count(self.address),
            })

            # Signature et envoi de la transaction
            signed_tx = self.w3.eth.account.sign_transaction(tx, self.account.key)
            tx_hash = self.w3.eth.send_raw_transaction(signed_tx.rawTransaction)
            return self.w3.eth.wait_for_transaction_receipt(tx_hash)

        except Exception as e:
            print(f"Erreur lors du swap: {str(e)}")
            return None

    def monitor_new_tokens(self, target_fid, callback):
        """Monitore les nouveaux tokens pour un FID spécifique"""
        last_checked_block = self.w3.eth.block_number
        
        while True:
            current_block = self.w3.eth.block_number
            if current_block > last_checked_block:
                tokens = self.get_clanker_tokens(target_fid)
                if tokens:
                    for token in tokens:
                        # Vérifier si le token est nouveau
                        if token.get('blockNumber', 0) > last_checked_block:
                            callback(token)
                last_checked_block = current_block 

    def get_amount_out(self, weth_address, token_address, amount_in_wei, slippage):
        """Utilise le Quoter Uniswap V3 pour estimer le minOut avec slippage"""
        try:
            quoter_abi = [{
                "inputs": [
                    {"internalType": "address", "name": "tokenIn", "type": "address"},
                    {"internalType": "address", "name": "tokenOut", "type": "address"},
                    {"internalType": "uint24", "name": "fee", "type": "uint24"},
                    {"internalType": "uint256", "name": "amountIn", "type": "uint256"},
                    {"internalType": "uint160", "name": "sqrtPriceLimitX96", "type": "uint160"}
                ],
                "name": "quoteExactInputSingle",
                "outputs": [
                    {"internalType": "uint256", "name": "amountOut", "type": "uint256"}
                ],
                "stateMutability": "view",
                "type": "function"
            }]
            quoter = self.w3.eth.contract(address=self.UNISWAP_V3_QUOTER, abi=quoter_abi)
            amount_out = quoter.functions.quoteExactInputSingle(
                weth_address,
                token_address,
                3000,
                amount_in_wei,
                0
            ).call()
            min_out = int(amount_out * (1 - slippage / 100))
            return min_out
        except Exception as e:
            print(f"Erreur get_amount_out: {str(e)}")
            return 0

    def swap_weth_for_token(self, router_address, weth_address, token_address, amount_in_wei, min_out=0):
        """Effectue un swap WETH -> token via Uniswap v3 (exactInputSingle), retourne le hash de la transaction."""
        try:
            # Utilise toujours le routeur officiel
            router = self.w3.eth.contract(address=self.UNISWAP_V3_ROUTER, abi=self.ROUTER_ABI)
            
            # Vérification du solde WETH
            weth_balance = self.w3.eth.get_balance(self.address)
            if weth_balance < amount_in_wei:
                raise Exception(f"Solde WETH insuffisant: {Web3.from_wei(weth_balance, 'ether')} WETH < {Web3.from_wei(amount_in_wei, 'ether')} WETH requis")

            # Approve WETH if needed
            approve_tx = self.approve_weth(amount_in_wei)
            if not approve_tx:
                raise Exception("Échec de l'approbation WETH")

            params = {
                'tokenIn': weth_address,
                'tokenOut': token_address,  # le token cible, PAS la pool
                'fee': 3000,
                'recipient': self.address,
                'deadline': self.w3.eth.get_block('latest').timestamp + 300,
                'amountIn': amount_in_wei,
                'amountOutMinimum': min_out,
                'sqrtPriceLimitX96': 0
            }

            # Simulation de la transaction avant envoi
            try:
                router.functions.exactInputSingle(params).call({
                    'from': self.address,
                    'value': 0
                })
            except Exception as e:
                raise Exception(f"Échec de la simulation du swap: {str(e)}")

            tx = router.functions.exactInputSingle(params).build_transaction({
                'from': self.address,
                'gas': 300000,
                'gasPrice': self.w3.eth.gas_price,
                'nonce': self.w3.eth.get_transaction_count(self.address),
            })

            signed_tx = self.w3.eth.account.sign_transaction(tx, self.account.key)
            tx_hash = self.w3.eth.send_raw_transaction(signed_tx.rawTransaction)
            
            # Attente de la confirmation et vérification du statut
            receipt = self.w3.eth.wait_for_transaction_receipt(tx_hash)
            if receipt['status'] == 0:
                # Récupération de la raison de l'échec
                try:
                    tx = self.w3.eth.get_transaction(tx_hash)
                    result = self.w3.eth.call(tx, block_identifier=receipt['blockNumber']-1)
                    raise Exception(f"Transaction échouée: {result}")
                except Exception as e:
                    raise Exception(f"Transaction échouée: {str(e)}")
            
            return tx_hash.hex()
        except Exception as e:
            print(f"Erreur détaillée lors du swap_weth_for_token: {str(e)}")
            return None

    def swap_eth_for_token(self, token_address, amount_in_wei, min_out=0):
        """
        Effectue un swap ETH natif -> token via Uniswap V3 (exactInputSingle).
        Vérifie d'abord la liquidité des pools et utilise le meilleur fee tier.
        """
        try:
            # 1. Vérification du solde ETH
            eth_balance = self.w3.eth.get_balance(self.address)
            if eth_balance < amount_in_wei:
                raise Exception(f"Solde ETH insuffisant: {Web3.from_wei(eth_balance, 'ether')} ETH < {Web3.from_wei(amount_in_wei, 'ether')} ETH requis")

            # 2. Vérification des pools pour chaque fee tier
            fee_tiers = [500, 3000, 10000]  # 0.05%, 0.3%, 1%
            best_pool = None
            best_liquidity = 0

            factory_contract = self.w3.eth.contract(
                address="0x33128a8fC17869897dcE68Ed026d694621f6FDfD",  # Uniswap V3 Factory
                abi=[{
                    "inputs": [
                        {"internalType": "address", "name": "tokenA", "type": "address"},
                        {"internalType": "address", "name": "tokenB", "type": "address"},
                        {"internalType": "uint24", "name": "fee", "type": "uint24"}
                    ],
                    "name": "getPool",
                    "outputs": [{"internalType": "address", "name": "", "type": "address"}],
                    "stateMutability": "view",
                    "type": "function"
                }]
            )

            for fee in fee_tiers:
                try:
                    pool_address = factory_contract.functions.getPool(
                        self.WETH_ADDRESS,
                        token_address,
                        fee
                    ).call()

                    if pool_address != "0x0000000000000000000000000000000000000000":
                        # Vérifier la liquidité
                        pool_contract = self.w3.eth.contract(
                            address=pool_address,
                            abi=[{
                                "inputs": [],
                                "name": "liquidity",
                                "outputs": [{"internalType": "uint128", "name": "", "type": "uint128"}],
                                "stateMutability": "view",
                                "type": "function"
                            }]
                        )
                        liquidity = pool_contract.functions.liquidity().call()
                        
                        if liquidity > best_liquidity:
                            best_liquidity = liquidity
                            best_pool = (fee, pool_address)
                except Exception as e:
                    print(f"Erreur lors de la vérification du pool {fee/10000}%: {str(e)}")
                    continue

            if not best_pool:
                raise Exception("Aucun pool avec liquidité trouvé")

            # 3. Construction des paramètres du swap
            params = {
                'tokenIn': self.WETH_ADDRESS,
                'tokenOut': token_address,
                'fee': best_pool[0],
                'recipient': self.address,
                'deadline': int(time.time()) + 300,
                'amountIn': amount_in_wei,
                'amountOutMinimum': min_out,
                'sqrtPriceLimitX96': 0
            }

            # 4. Simulation de la transaction
            try:
                self.router_contract.functions.exactInputSingle(params).call({
                    'from': self.address,
                    'value': amount_in_wei
                })
            except Exception as e:
                raise Exception(f"Échec de la simulation du swap: {str(e)}")

            # 5. Construction et envoi de la transaction
            tx = self.router_contract.functions.exactInputSingle(params).build_transaction({
                'from': self.address,
                'value': amount_in_wei,
                'gas': 500000,  # Gas limit plus élevé pour plus de sécurité
                'maxFeePerGas': int(self.w3.eth.get_block('latest').baseFeePerGas * 2.5 + self.w3.eth.max_priority_fee),
                'maxPriorityFeePerGas': self.w3.eth.max_priority_fee,
                'nonce': self.w3.eth.get_transaction_count(self.address),
                'chainId': 8453  # Base Mainnet
            })

            # 6. Signature et envoi
            signed_tx = self.w3.eth.account.sign_transaction(tx, self.account.key)
            tx_hash = self.w3.eth.send_raw_transaction(signed_tx.rawTransaction)
            
            # 7. Attente de la confirmation avec retry
            max_retries = 3
            for i in range(max_retries):
                try:
                    receipt = self.w3.eth.wait_for_transaction_receipt(tx_hash, timeout=60)
                    if receipt['status'] == 1:
                        return tx_hash.hex()
                    else:
                        raise Exception(f"Transaction échouée. Voir https://basescan.org/tx/{tx_hash.hex()}")
                except Exception as e:
                    if i == max_retries - 1:
                        raise Exception(f"Échec de la confirmation après {max_retries} tentatives: {str(e)}")
                    time.sleep(2 ** i)  # Backoff exponentiel

        except Exception as e:
            print(f"Erreur détaillée lors du swap ETH -> token: {str(e)}")
            return str(e)

    def check_pool_exists(self, token_address, amount_in_wei=10**15):
        """
        Vérifie si une pool Uniswap V3 WETH/token existe et a de la liquidité.
        Retourne True si la pool existe et amountOut > 0, False sinon.
        """
        try:
            quoter_abi = [{
                "inputs": [
                    {"internalType": "address", "name": "tokenIn", "type": "address"},
                    {"internalType": "address", "name": "tokenOut", "type": "address"},
                    {"internalType": "uint24", "name": "fee", "type": "uint24"},
                    {"internalType": "uint256", "name": "amountIn", "type": "uint256"},
                    {"internalType": "uint160", "name": "sqrtPriceLimitX96", "type": "uint160"}
                ],
                "name": "quoteExactInputSingle",
                "outputs": [
                    {"internalType": "uint256", "name": "amountOut", "type": "uint256"}
                ],
                "stateMutability": "view",
                "type": "function"
            }]
            quoter = self.w3.eth.contract(address=self.UNISWAP_V3_QUOTER, abi=quoter_abi)
            amount_out = quoter.functions.quoteExactInputSingle(
                self.WETH_ADDRESS,
                token_address,
                3000,
                amount_in_wei,
                0
            ).call()
            return amount_out > 0
        except Exception as e:
            print(f"[POOL CHECK] Erreur: {str(e)}")
            return False

async def buy_token(update: Update, context: CallbackContext):
    """Commande /buy : achat/swap Uniswap V3 fee 1% (logique robuste, RPC Railway, gestion Telegram asynchrone)"""
    try:
        if len(context.args) != 2:
            await update.message.reply_text(
                "❌ Format incorrect\nUtilisation : /buy <adresse_token> <montant_eth>\nExemple : /buy 0x123... 0.1"
            )
            return
        token_address = context.args[0]
        try:
            amount_eth = float(context.args[1])
        except ValueError:
            await update.message.reply_text("❌ Le montant doit être un nombre valide")
            return
        if not Web3.is_address(token_address):
            await update.message.reply_text("❌ Adresse de token invalide")
            return
        # Setup Web3
        rpc_url = os.getenv("QUICKNODE_RPC") or os.getenv("RPC_URL") or "https://mainnet.base.org"
        w3 = Web3(Web3.HTTPProvider(rpc_url))
        private_key = os.getenv("PRIVATE_KEY")
        if not private_key:
            await update.message.reply_text("❌ Clé privée manquante dans Railway")
            return
        account = Account.from_key(private_key)
        address = account.address
        # Vérif solde
        balance = w3.eth.get_balance(address)
        balance_eth = w3.from_wei(balance, 'ether')
        await update.message.reply_text(f"💰 Solde actuel : {balance_eth:.4f} ETH\n🎯 Montant à acheter : {amount_eth:.4f} ETH")
        amount_wei = w3.to_wei(amount_eth, 'ether')
        if balance < amount_wei:
            await update.message.reply_text(f"❌ Solde insuffisant : {balance_eth:.4f} ETH < {amount_eth:.4f} ETH")
            return
        # Recherche pool fee 1% dans les deux sens
        FACTORY = w3.to_checksum_address("0x33128a8fC17869897dcE68Ed026d694621f6FDfD")
        WETH = w3.to_checksum_address("0x4200000000000000000000000000000000000006")
        FEE = 10000
        factory_abi = [{
            "inputs": [
                {"internalType": "address", "name": "tokenA", "type": "address"},
                {"internalType": "address", "name": "tokenB", "type": "address"},
                {"internalType": "uint24", "name": "fee", "type": "uint24"}
            ],
            "name": "getPool",
            "outputs": [{"internalType": "address", "name": "", "type": "address"}],
            "stateMutability": "view",
            "type": "function"
        }]
        pool = None
        direction = None
        token = w3.to_checksum_address(token_address)
        factory = w3.eth.contract(address=FACTORY, abi=factory_abi)
        # Essai WETH -> token
        pool_addr = factory.functions.getPool(WETH, token, FEE).call()
        if pool_addr != "0x0000000000000000000000000000000000000000":
            direction = 'WETH_TO_TOKEN'
            pool = pool_addr
        else:
            # Essai token -> WETH
            pool_addr = factory.functions.getPool(token, WETH, FEE).call()
            if pool_addr != "0x0000000000000000000000000000000000000000":
                direction = 'TOKEN_TO_WETH'
                pool = pool_addr
        if not pool:
            await update.message.reply_text("❌ Pas de pool 1% trouvée dans les deux sens.")
            return
        # Vérif liquidité
        pool_abi = [
            {"inputs": [], "name": "liquidity", "outputs": [{"internalType": "uint128", "name": "", "type": "uint128"}], "stateMutability": "view", "type": "function"}
        ]
        pool_contract = w3.eth.contract(address=pool, abi=pool_abi)
        liquidity = pool_contract.functions.liquidity().call()
        if liquidity == 0:
            await update.message.reply_text(f"❌ Pool trouvée ({pool}) mais pas de liquidité.")
            return
        await update.message.reply_text(f"✅ Pool trouvée : {pool}\n💧 Liquidité : {liquidity}")
        # Construction du path Uniswap V3 (toujours WETH -> token)
        def encode_path(token_in, fee, token_out):
            return bytes.fromhex(token_in[2:] + hex(fee)[2:].zfill(6) + token_out[2:])
        if direction == 'WETH_TO_TOKEN':
            path = encode_path(WETH, FEE, token)
        else:
            path = encode_path(token, FEE, WETH)
        # Construction de la tx
        router_addr = w3.to_checksum_address("0x2626664c2603336E57B271c5C0b26F421741e481")
        router_abi = [
            {
                "inputs": [
                    {
                        "components": [
                            {"internalType": "bytes", "name": "path", "type": "bytes"},
                            {"internalType": "address", "name": "recipient", "type": "address"},
                            {"internalType": "uint256", "name": "amountIn", "type": "uint256"},
                            {"internalType": "uint256", "name": "amountOutMinimum", "type": "uint256"}
                        ],
                        "internalType": "struct ISwapRouter.ExactInputParams",
                        "name": "params",
                        "type": "tuple"
                    }
                ],
                "name": "exactInput",
                "outputs": [{"internalType": "uint256", "name": "amountOut", "type": "uint256"}],
                "stateMutability": "payable",
                "type": "function"
            }
        ]
        router = w3.eth.contract(address=router_addr, abi=router_abi)
        params = {
            'path': path,
            'recipient': address,
            'amountIn': amount_wei,
            'amountOutMinimum': 0
        }
        nonce = w3.eth.get_transaction_count(address)
        base_fee = w3.eth.get_block('latest').baseFeePerGas
        priority_fee = w3.eth.max_priority_fee
        max_fee_per_gas = int(base_fee * 2.5 + priority_fee)
        tx = router.functions.exactInput(params).build_transaction({
            'chainId': 8453,
            'gas': 500000,
            'maxFeePerGas': max_fee_per_gas,
            'maxPriorityFeePerGas': priority_fee,
            'nonce': nonce,
            'value': amount_wei,
            'from': address
        })
        signed_tx = w3.eth.account.sign_transaction(tx, private_key)
        tx_hash = w3.eth.send_raw_transaction(signed_tx.rawTransaction)
        tx_link = f"https://basescan.org/tx/{tx_hash.hex()}"
        await update.message.reply_text(f"✅ Transaction envoyée !\nHash : `{tx_hash.hex()}`\n🔍 [Voir sur Basescan]({tx_link})", parse_mode='Markdown')
        try:
            receipt = w3.eth.wait_for_transaction_receipt(tx_hash, timeout=60)
            if receipt.status == 1:
                await update.message.reply_text("✅ Transaction confirmée avec succès!")
            else:
                await update.message.reply_text("❌ La transaction a échoué")
        except Exception as e:
            await update.message.reply_text(f"⚠️ Timeout en attendant la confirmation.\nVérifiez le statut sur Basescan : [Voir transaction]({tx_link})", parse_mode='Markdown')
    except Exception as e:
        await update.message.reply_text(f"❌ Erreur : {str(e)}")

# Dictionnaire pour stocker les snipes actifs
active_snipes = {}
last_token_id = None

# Monitoring des nouveaux tokens Clanker
async def monitor_new_clankers(app):
    global last_token_id
    while True:
        try:
            resp = requests.get("https://www.clanker.world/api/tokens?sort=desc&page=1")
            if resp.status_code == 200:
                data = resp.json()
                if data.get("data"):
                    latest = data["data"][0]
                    if latest["id"] != last_token_id:
                        last_token_id = latest["id"]
                        fid = str(latest.get("requestor_fid"))
                        if fid in active_snipes:
                            snipe = active_snipes[fid]
                            user_id = snipe["user_id"]
                            amount_eth = snipe["amount_eth"]
                            # Message Telegram
                            await app.bot.send_message(
                                chat_id=user_id,
                                text=f"🎯 Nouveau token détecté pour FID {fid} :\n"
                                     f"Nom: {latest.get('name')}\n"
                                     f"Symbole: {latest.get('symbol')}\n"
                                     f"Contract: {latest.get('contract_address')}\n"
                                     f"Pool: {latest.get('pool_address')}\n"
                                     f"Montant: {amount_eth} ETH\n"
                                     f"Déclenchement du snipe..."
                            )
                            # Achat automatique
                            await buy_token_auto(app, user_id, latest["contract_address"], amount_eth)
        except Exception as e:
            print(f"[MONITOR] Erreur: {str(e)}")
        await asyncio.sleep(0.5)

# Achat automatique (même logique que /buy)
async def buy_token_auto(app, user_id, token_address, amount_eth):
    class FakeMessage:
        def __init__(self, user_id):
            self.chat_id = user_id
        async def reply_text(self, text, **kwargs):
            await app.bot.send_message(chat_id=self.chat_id, text=text, **kwargs)
    class FakeUpdate:
        def __init__(self, user_id):
            self.message = FakeMessage(user_id)
    class FakeContext:
        def __init__(self, token_address, amount_eth):
            self.args = [token_address, str(amount_eth)]
    fake_update = FakeUpdate(user_id)
    fake_context = FakeContext(token_address, amount_eth)
    await buy_token(fake_update, fake_context)

# Commande /snipe <FID> <amount en eth>
async def snipe_command(update: Update, context: CallbackContext):
    if len(context.args) != 2:
        await update.message.reply_text("❌ Format : /snipe <FID> <montant_eth>")
        return
    fid = context.args[0]
    try:
        amount_eth = float(context.args[1])
    except ValueError:
        await update.message.reply_text("❌ Montant ETH invalide")
        return
    user_id = update.effective_user.id
    active_snipes[fid] = {"amount_eth": amount_eth, "user_id": user_id}
    await update.message.reply_text(f"✅ Snipe activé pour FID {fid} avec {amount_eth} ETH.")

# Ajout du handler dans la fonction de démarrage du bot
# (à placer dans la fonction main ou équivalent)
# application.add_handler(CommandHandler("snipe", snipe_command))

# Démarrage du monitoring dans un thread séparé au lancement du bot
# (à placer dans la fonction main ou équivalent)
# asyncio.create_task(monitor_new_clankers(application))

# Ajoute la configuration complète du bot Telegram
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

load_dotenv()
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
if not TELEGRAM_TOKEN:
    raise ValueError("TELEGRAM_TOKEN non trouvé dans le fichier .env")

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 Bienvenue sur ClankerSniper Bot !\n\n"
        "Commandes disponibles :\n"
        "/buy <adresse_token> <montant_eth> - Acheter un token\n"
        "/snipe <FID> <montant_eth> - Snipe auto sur FID\n"
        "/help - Afficher l'aide"
    )

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "📚 Guide d'utilisation :\n\n"
        "1. Pour acheter un token :\n"
        "   /buy <adresse_token> <montant_eth>\n"
        "   Exemple : /buy 0x123... 0.1\n\n"
        "2. Pour snip auto un FID :\n"
        "   /snipe <FID> <montant_eth>\n"
        "   Exemple : /snipe 123456 0.1\n\n"
        "Le bot surveille automatiquement les nouveaux tokens Clanker et déclenche un achat si un snipe est configuré pour le FID concerné."
    )

async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    error = context.error
    logger.error("Exception while handling an update:", exc_info=error)
    if update and update.effective_message:
        error_message = f"❌ Erreur : {str(error)}"
        if hasattr(error, 'message'):
            error_message = f"❌ Erreur : {error.message}"
        elif hasattr(error, 'args') and error.args:
            error_message = f"❌ Erreur : {error.args[0]}"
        if hasattr(error, 'data'):
            error_message += f"\n\nDétails : {error.data}"
        await update.effective_message.reply_text(error_message)

def main():
    application = Application.builder().token(TELEGRAM_TOKEN).build()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("buy", buy_token))
    application.add_handler(CommandHandler("snipe", snipe_command))
    application.add_error_handler(error_handler)
    # Démarrage du monitoring asynchrone
    application.post_init = lambda app: asyncio.create_task(monitor_new_clankers(app))
    application.run_polling(allowed_updates=Update.ALL_TYPES, drop_pending_updates=True)

if __name__ == '__main__':
    main() 