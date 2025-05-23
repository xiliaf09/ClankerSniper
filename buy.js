// buy.js
require('dotenv').config();
const { ethers } = require("ethers");

// Paramètres Uniswap V3 sur Base
const ROUTER_ADDRESS = "0x2626664c2603336E57B271c5C0b26F421741e481";
const WETH_ADDRESS = "0x4200000000000000000000000000000000000006";
const ROUTER_ABI = [
  {
    "inputs": [
      {
        "components": [
          { "internalType": "address", "name": "tokenIn", "type": "address" },
          { "internalType": "address", "name": "tokenOut", "type": "address" },
          { "internalType": "uint24", "name": "fee", "type": "uint24" },
          { "internalType": "address", "name": "recipient", "type": "address" },
          { "internalType": "uint256", "name": "deadline", "type": "uint256" },
          { "internalType": "uint256", "name": "amountIn", "type": "uint256" },
          { "internalType": "uint256", "name": "amountOutMinimum", "type": "uint256" },
          { "internalType": "uint160", "name": "sqrtPriceLimitX96", "type": "uint160" }
        ],
        "internalType": "struct ISwapRouter.ExactInputSingleParams",
        "name": "params",
        "type": "tuple"
      }
    ],
    "name": "exactInputSingle",
    "outputs": [
      { "internalType": "uint256", "name": "amountOut", "type": "uint256" }
    ],
    "stateMutability": "payable",
    "type": "function"
  }
];

const FACTORY_ADDRESS = "0x33128a8fC17869897dcE68Ed026d694621f6FDfD";
const FACTORY_ABI = [
  {
    "inputs": [
      { "internalType": "address", "name": "tokenA", "type": "address" },
      { "internalType": "address", "name": "tokenB", "type": "address" },
      { "internalType": "uint24", "name": "fee", "type": "uint24" }
    ],
    "name": "getPool",
    "outputs": [{ "internalType": "address", "name": "", "type": "address" }],
    "stateMutability": "view",
    "type": "function"
  }
];

const POOL_ABI = [
  {
    "inputs": [],
    "name": "liquidity",
    "outputs": [{ "internalType": "uint128", "name": "", "type": "uint128" }],
    "stateMutability": "view",
    "type": "function"
  }
];

// Récupère les arguments
const [,, poolAddressRaw, amountEth] = process.argv;

// Correction automatique de l'adresse en minuscules
const poolAddress = poolAddressRaw ? poolAddressRaw.toLowerCase() : null;

if (!poolAddress || !amountEth) {
  console.error("Usage: node buy.js <pool_address> <amount_eth>");
  process.exit(1);
}

const PRIVATE_KEY = process.env.PRIVATE_KEY;
const RPC_URL = process.env.RPC_URL || "https://mainnet.base.org";

if (!PRIVATE_KEY) {
  console.error("PRIVATE_KEY manquante dans les variables d'environnement.");
  process.exit(1);
}

async function main() {
  const provider = new ethers.JsonRpcProvider(RPC_URL);
  const wallet = new ethers.Wallet(PRIVATE_KEY, provider);
  const router = new ethers.Contract(ROUTER_ADDRESS, ROUTER_ABI, wallet);

  // Vérification du solde ETH
  const balance = await provider.getBalance(wallet.address);
  console.log("Solde ETH:", ethers.formatEther(balance), "ETH");
  
  const amountIn = ethers.parseEther(amountEth);
  if (balance < amountIn) {
    console.error("ERROR", "Solde ETH insuffisant");
    process.exit(2);
  }

  // Vérification de la liquidité
  const pool = new ethers.Contract(poolAddress, POOL_ABI, provider);
  const liquidity = await pool.liquidity();
  console.log("Liquidité de la pool:", liquidity.toString());
  
  if (liquidity === 0n) {
    console.error("ERROR", "Pool n'a pas de liquidité");
    process.exit(2);
  }

  const deadline = Math.floor(Date.now() / 1000) + 300;
  console.log("Deadline:", new Date(deadline * 1000).toISOString());

  const params = {
    tokenIn: WETH_ADDRESS,
    tokenOut: tokenAddress,
    fee: 3000,
    recipient: wallet.address,
    deadline: deadline,
    amountIn: amountIn,
    amountOutMinimum: 0,
    sqrtPriceLimitX96: 0
  };

  console.log("Paramètres de la transaction:", {
    tokenIn: params.tokenIn,
    tokenOut: params.tokenOut,
    amountIn: ethers.formatEther(params.amountIn),
    recipient: params.recipient
  });

  try {
    // Estimation du gas
    const gasEstimate = await router.exactInputSingle.estimateGas(
      params,
      { value: amountIn }
    );
    console.log("Estimation gas:", gasEstimate.toString());

    const tx = await router.exactInputSingle(
      params,
      { 
        value: amountIn, 
        gasLimit: Math.floor(gasEstimate * 1.2) // +20% de marge
      }
    );
    console.log("SUCCESS", tx.hash);
  } catch (e) {
    console.error("ERROR", e.reason || e.message || e);
    process.exit(2);
  }
}

main(); 