import json
import requests
from web3 import Web3
from eth_account import Account
from web3.middleware import geth_poa_middleware

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
        Reproduit exactement le processus de la tx de référence.
        """
        try:
            # 1. Vérification du solde ETH
            eth_balance = self.w3.eth.get_balance(self.address)
            if eth_balance < amount_in_wei:
                raise Exception(f"Solde ETH insuffisant: {Web3.from_wei(eth_balance, 'ether')} ETH < {Web3.from_wei(amount_in_wei, 'ether')} ETH requis")

            # 2. Construction des paramètres du swap
            params = {
                'tokenIn': self.WETH_ADDRESS,  # WETH (le routeur wrappe l'ETH automatiquement)
                'tokenOut': token_address,     # Token cible
                'fee': 3000,                   # 0.3% fee tier
                'recipient': self.address,     # On reçoit les tokens
                'deadline': self.w3.eth.get_block('latest').timestamp + 300,  # 5 minutes
                'amountIn': amount_in_wei,     # Montant ETH en wei
                'amountOutMinimum': min_out,   # Protection contre le slippage
                'sqrtPriceLimitX96': 0         # Pas de limite de prix
            }

            # 3. Simulation de la transaction
            try:
                self.router_contract.functions.exactInputSingle(params).call({
                    'from': self.address,
                    'value': amount_in_wei
                })
            except Exception as e:
                raise Exception(f"Échec de la simulation: {str(e)}")

            # 4. Construction et envoi de la transaction
            tx = self.router_contract.functions.exactInputSingle(params).build_transaction({
                'from': self.address,
                'value': amount_in_wei,  # ETH natif envoyé
                'gas': 300000,           # Gas limit suffisant
                'gasPrice': self.w3.eth.gas_price,
                'nonce': self.w3.eth.get_transaction_count(self.address),
            })

            # 5. Signature et envoi
            signed_tx = self.w3.eth.account.sign_transaction(tx, self.account.key)
            tx_hash = self.w3.eth.send_raw_transaction(signed_tx.rawTransaction)
            
            # 6. Attente de la confirmation
            receipt = self.w3.eth.wait_for_transaction_receipt(tx_hash)
            
            # 7. Vérification du statut
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
            print(f"Erreur détaillée lors du swap ETH -> token: {str(e)}")
            return None 